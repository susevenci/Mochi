"""WebSocket 接入层：连接管理、信封编解码、握手、心跳、对话分发（计划书 6.1–6.2）。

关键设计：对话生成放在独立 Task 里跑，接收循环保持可用——
否则 ``chat.interrupt`` 会因为正在生成而收不到（规划文档 1.3.5）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config.settings import Settings
from app.emotion.engine import EmotionEngine
from app.gateway.auth import is_authorized
from app.gateway.errors import ErrorCode, error_envelope
from app.gateway.protocol import (
    PROTOCOL_VERSION,
    ChatAgentDeltaPayload,
    ChatAgentFinalPayload,
    ChatUserInputPayload,
    Envelope,
    InteractionEventPayload,
    MessageType,
    PerformanceCuePayload,
    SysHelloAckPayload,
    SysPongPayload,
    build_envelope,
)
from app.orchestration.events import CuePayload, EventSink, FinalPayload
from app.orchestration.orchestrator import Orchestrator
from app.utils.ids import ulid

log = logging.getLogger(__name__)

WS_CLOSE_UNAUTHORIZED = 4401


class ConnectionManager:
    """连接集合 + 主动推送广播（情绪事件、主动搭话等后续复用）。"""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    def add(self, ws: WebSocket) -> None:
        self._connections.add(ws)

    def discard(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    @property
    def count(self) -> int:
        return len(self._connections)

    async def broadcast(self, envelope: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(envelope)
            except RuntimeError:
                dead.append(ws)
        for ws in dead:
            self.discard(ws)


class WSSink:
    """把编排层事件转成 WS 信封（EventSink 的 WebSocket 实现）。"""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self._index = 0

    async def delta(self, turn_id: str, text: str) -> None:
        payload = ChatAgentDeltaPayload(delta=text, index=self._index)
        self._index += 1
        await self._ws.send_json(_envelope(MessageType.CHAT_AGENT_DELTA, payload, turn_id))

    async def final(self, turn_id: str, payload: FinalPayload) -> None:
        body = ChatAgentFinalPayload(
            text=payload.text,
            route=payload.route,
            emotion=payload.emotion,
            action=payload.action,
            error=payload.error,
            first_token_ms=payload.first_token_ms,
            latency_ms=payload.latency_ms,
        )
        await self._ws.send_json(_envelope(MessageType.CHAT_AGENT_FINAL, body, turn_id))

    async def error(self, turn_id: str, code: str, detail: str = "") -> None:
        await self._ws.send_json(
            error_envelope(ErrorCode.INTERNAL, detail=detail or code, turn_id=turn_id)
        )

    async def cue(self, turn_id: str, payload: CuePayload) -> None:
        body = PerformanceCuePayload(
            emotion_label=payload.emotion_label,
            motion=payload.motion,
            expression=payload.expression,
            priority=payload.priority,
            expression_weight=payload.expression_weight,
            secondary_expression=payload.secondary_expression,
            secondary_weight=payload.secondary_weight,
            auto_release_ms=payload.auto_release_ms,
            tts=payload.tts,
            params=payload.params,
            style_hints=payload.style_hints,
        )
        await self._ws.send_json(_envelope(MessageType.PERFORMANCE_CUE, body, turn_id))


def _envelope(env_type: str, payload: Any, turn_id: str | None = None) -> dict[str, Any]:
    data = payload.model_dump() if hasattr(payload, "model_dump") else payload
    return build_envelope(env_type, data, turn_id=turn_id).model_dump(mode="json")


def _on_chat_task_done(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("chat task failed: %s", exc, exc_info=exc)


async def _handle_chat(env: Envelope, ws: WebSocket, orchestrator: Orchestrator) -> None:
    try:
        payload = ChatUserInputPayload.model_validate(env.payload)
    except ValidationError as exc:
        detail = str(exc.errors()[0].get("msg", "invalid payload"))
        await ws.send_json(
            error_envelope(ErrorCode.BAD_ENVELOPE, detail=detail, turn_id=env.turn_id)
        )
        return
    turn_id = env.turn_id or ulid()
    sink: EventSink = WSSink(ws)
    task = asyncio.create_task(orchestrator.handle_chat(turn_id, payload.text, sink))
    task.add_done_callback(_on_chat_task_done)


async def _dispatch(
    raw: str,
    ws: WebSocket,
    server_version: str,
    orchestrator: Orchestrator | None,
    emotion: EmotionEngine | None = None,
) -> None:
    """单条消息的分发。任何异常都转成 ``sys.error``，绝不中断连接。"""
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        await ws.send_json(error_envelope(ErrorCode.BAD_JSON))
        return

    try:
        env = Envelope.model_validate(decoded)
    except ValidationError as exc:
        detail = exc.errors()[0].get("msg", "invalid envelope")
        await ws.send_json(error_envelope(ErrorCode.BAD_ENVELOPE, detail=str(detail)))
        return

    if env.v != PROTOCOL_VERSION:
        await ws.send_json(
            error_envelope(
                ErrorCode.PROTOCOL_MISMATCH,
                detail=f"expected v={PROTOCOL_VERSION}, got v={env.v}",
                turn_id=env.turn_id,
            )
        )
        return

    if env.type == MessageType.SYS_HELLO:
        ack = SysHelloAckPayload(
            server_version=server_version,
            server_time=time.time(),
            emotion=emotion.snapshot().to_payload() if emotion is not None else None,
        )
        await ws.send_json(_envelope(MessageType.SYS_HELLO_ACK, ack, env.turn_id))
        return
    if env.type == MessageType.SYS_PING:
        pong = SysPongPayload(echo_ts=env.payload.get("ts"), server_time=time.time())
        await ws.send_json(_envelope(MessageType.SYS_PONG, pong, env.turn_id))
        return
    if env.type == MessageType.CHAT_USER_INPUT:
        if orchestrator is None:
            await ws.send_json(error_envelope(ErrorCode.INTERNAL, detail="orchestrator not ready"))
            return
        await _handle_chat(env, ws, orchestrator)
        return
    if env.type == MessageType.CHAT_INTERRUPT:
        if orchestrator is not None and env.turn_id:
            cancelled = orchestrator.interrupt(env.turn_id)
            log.info("interrupt turn=%s accepted=%s", env.turn_id, cancelled)
        return
    if env.type == MessageType.INTERACTION_EVENT:
        try:
            event = InteractionEventPayload.model_validate(env.payload)
        except ValidationError as exc:
            detail = str(exc.errors()[0].get("msg", "invalid payload"))
            await ws.send_json(
                error_envelope(ErrorCode.BAD_ENVELOPE, detail=detail, turn_id=env.turn_id)
            )
            return
        log.info(
            "interaction type=%s area=%s count=%d at=(%.0f,%.0f)",
            event.type,
            event.area,
            event.count,
            event.x,
            event.y,
        )
        if emotion is not None:
            await emotion.apply_interaction(event.type, count=event.count, area=event.area)
        return

    await ws.send_json(error_envelope(ErrorCode.UNKNOWN_TYPE, detail=env.type, turn_id=env.turn_id))


def create_ws_router(
    settings: Settings,
    manager: ConnectionManager,
    server_version: str,
    orchestrator: Orchestrator | None = None,
    emotion: EmotionEngine | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        if not is_authorized(ws, settings.server_token):
            await ws.close(code=WS_CLOSE_UNAUTHORIZED)
            return

        await ws.accept()
        manager.add(ws)
        log.info("ws connected total=%d", manager.count)
        try:
            while True:
                raw = await ws.receive_text()
                await _dispatch(raw, ws, server_version, orchestrator, emotion)
        except WebSocketDisconnect:
            pass
        finally:
            manager.discard(ws)
            log.info("ws disconnected total=%d", manager.count)

    return router
