"""WS 消息契约（计划书第 6 章）。

本文件是**前后端唯一真相源**：由 ``scripts/export_schema.py`` 导出 JSON Schema，
再由 ``scripts/gen-types.mjs`` 生成前端 TS 类型。禁止手改生成物（不变量 I4）。
S0 只定义信封与 ``sys.*`` 消息；``chat.*`` / ``emotion.*`` 在 S1/S3 扩充。
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.utils.ids import ulid

PROTOCOL_VERSION = 1


class MessageType(StrEnum):
    """消息类型，采用 ``域.动作`` 命名（计划书 6.3）。"""

    SYS_HELLO = "sys.hello"
    SYS_HELLO_ACK = "sys.hello_ack"
    SYS_PING = "sys.ping"
    SYS_PONG = "sys.pong"
    SYS_ERROR = "sys.error"
    SYS_STATUS = "sys.status"
    CHAT_USER_INPUT = "chat.user_input"
    CHAT_AGENT_DELTA = "chat.agent_delta"
    CHAT_AGENT_FINAL = "chat.agent_final"
    CHAT_INTERRUPT = "chat.interrupt"
    PERFORMANCE_CUE = "performance.cue"
    INTERACTION_EVENT = "interaction.event"


class Envelope(BaseModel):
    """所有 WS 文本消息的统一信封（计划书 6.2）。

    六个字段在**线格式上全部必填**（``turn_id`` 允许为 null），
    这样导出的 JSON Schema 不会把 ``id`` / ``ts`` 误标为可选。
    发送侧请用 :func:`build_envelope` 构造。
    """

    model_config = ConfigDict(extra="forbid")

    v: int
    type: str
    id: str
    ts: float
    turn_id: str | None = None
    payload: dict[str, Any]


def build_envelope(
    env_type: str,
    payload: dict[str, Any] | None = None,
    *,
    turn_id: str | None = None,
) -> Envelope:
    """构造一条出站信封，自动填充 ``v`` / ``id`` / ``ts``。"""
    return Envelope(
        v=PROTOCOL_VERSION,
        type=env_type,
        id=ulid(),
        ts=time.time(),
        turn_id=turn_id,
        payload=payload or {},
    )


class SysHelloAckPayload(BaseModel):
    """握手响应，含全量状态快照（S0 只含版本与时间）。"""

    server_version: str
    protocol: int = PROTOCOL_VERSION
    server_time: float
    emotion: dict[str, Any] | None = None


class SysPongPayload(BaseModel):
    echo_ts: float | None = None
    server_time: float


class SysErrorPayload(BaseModel):
    code: str
    detail: str | None = None
    retryable: bool = False


class ChatUserInputPayload(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    modality: str = "text"
    session_id: str = "sess_default"


class ChatAgentDeltaPayload(BaseModel):
    delta: str
    index: int = 0
    done: bool = False


class ChatAgentFinalPayload(BaseModel):
    text: str
    route: str
    emotion: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    error: str | None = None
    first_token_ms: int | None = None
    latency_ms: int | None = None


class ChatInterruptPayload(BaseModel):
    reason: str = "user"


class PerformanceCuePayload(BaseModel):
    emotion_label: str
    motion: str
    expression: str | None = None
    priority: str = "normal"


class InteractionEventPayload(BaseModel):
    """前端上报的交互事件（计划书 5.6.6）。

    ``type`` 即刺激标签（pat_head / touch_face / poke_body / teased / dragged），
    S3 的情感引擎把它转成刺激；S2 只做接收与日志。
    """

    type: str = Field(min_length=1, max_length=32)
    area: str = "body"
    count: int = Field(default=1, ge=1)
    x: float = 0.0
    y: float = 0.0
