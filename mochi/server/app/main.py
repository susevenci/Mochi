"""服务入口：FastAPI 应用装配、健康检查、REST 与 WS 挂载。

开发：``python -m uvicorn --app-dir server app.main:create_app --factory --reload``
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .bootstrap import bootstrap
from .config.character_card import CardLoader, Persona
from .config.llm_settings import LLMConfig, mask_key
from .config.settings import Settings
from .context import AppContext
from .emotion.labels import load_catalog as load_label_catalog
from .emotion.models import Stimulus, StimulusSource
from .emotion.stimuli.catalog import load_catalog as load_stimulus_catalog
from .emotion.transitions import load_transitions
from .gateway.auth import is_authorized
from .gateway.errors import ErrorCode
from .gateway.protocol import (
    PROTOCOL_VERSION,
    EmotionUpdatePayload,
    MessageType,
    ProactiveSpeakPayload,
    build_envelope,
)
from .gateway.ws import ConnectionManager, create_ws_router
from .orchestration.live2d_binding import scan_live2d_models as _scan_live2d_models
from .orchestration.live2d_binding import validate_binding
from .providers.base import LLMError
from .scheduler.reminders import ReminderScheduler

log = logging.getLogger(__name__)


class LLMConfigPatch(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    disable_thinking: bool | None = None


class StimulusRequest(BaseModel):
    tag: str = Field(min_length=1)
    magnitude: float = Field(default=1.0, ge=0.0, le=3.0)
    preferred_label: str | None = None


class AdvanceRequest(BaseModel):
    seconds: float = Field(gt=0.0, le=30 * 24 * 3600)


class MemorySessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=60)


class ProfileRequest(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=200)


class AgentConfigPatch(BaseModel):
    route_mode: Literal["auto", "chat_only", "force_agent"] | None = None


class PersonaPatch(BaseModel):
    reactivity: dict[str, float] | None = None
    decay_multiplier: float | None = Field(default=None, gt=0.1, le=5.0)
    refractory_seconds: float | None = Field(default=None, ge=0.0, le=120.0)
    dominance_recovery: float | None = Field(default=None, ge=0.0, le=0.1)
    baseline_mood: dict[str, float] | None = None
    label_bias: dict[str, float] | None = None
    forbidden_labels: list[str] | None = None


def _llm_view(config: LLMConfig) -> dict[str, Any]:
    """对外视图：只暴露 api_key 掩码，绝不返回明文。"""
    return {
        "base_url": config.base_url,
        "model": config.model,
        "disable_thinking": config.disable_thinking,
        "api_key_set": bool(config.api_key),
        "api_key_hint": mask_key(config.api_key),
        "source": config.source,
    }


def scan_live2d_models(root: Path) -> list[dict[str, Any]]:
    """兼容入口：扫描逻辑已移到 ``orchestration/live2d_binding.py``（与绑定校验共用）。"""
    return _scan_live2d_models(root)


def _envelope(env_type: str, payload: Any, turn_id: str | None = None) -> dict[str, Any]:
    data = payload.model_dump() if hasattr(payload, "model_dump") else payload
    return build_envelope(env_type, data, turn_id=turn_id).model_dump(mode="json")


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    ctx: AppContext = bootstrap(cfg)
    manager = ConnectionManager()

    async def broadcast_emotion(snapshot: Any) -> None:
        if manager.count == 0:
            return
        payload = EmotionUpdatePayload.model_validate(snapshot.to_payload())
        await manager.broadcast(_envelope(MessageType.EMOTION_UPDATE, payload))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await ctx.memory.start()

        async def emit_proactive(text: str, label: str) -> None:
            payload = ProactiveSpeakPayload(text=text, emotion_label=label, kind="report")
            await manager.broadcast(_envelope(MessageType.PROACTIVE_SPEAK, payload))

        ctx.orchestrator.set_report_sink(emit_proactive)
        reminder_scheduler = ReminderScheduler(
            memory=ctx.memory,
            emotion=ctx.emotion,
            emit=emit_proactive,
        )
        await reminder_scheduler.start()
        unsubscribe = ctx.emotion.subscribe(broadcast_emotion)
        await ctx.emotion.start()

        async def proactive_loop() -> None:
            while True:
                await asyncio.sleep(15.0)
                if manager.count == 0:
                    continue
                try:
                    intent = ctx.emotion.poll_proactive()
                    if intent is not None:
                        payload = ProactiveSpeakPayload(
                            text=intent.text,
                            emotion_label=intent.label,
                            kind=intent.kind,
                        )
                        await manager.broadcast(_envelope(MessageType.PROACTIVE_SPEAK, payload))
                        log.info("proactive speak kind=%s", intent.kind)
                except Exception as exc:  # noqa: BLE001 - 主动搭话失败不影响对话
                    log.warning("proactive loop error: %s", exc)

        proactive_task = asyncio.create_task(proactive_loop(), name="proactive")
        try:
            yield
        finally:
            proactive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await proactive_task
            unsubscribe()
            await reminder_scheduler.stop()
            await ctx.emotion.stop()
            await ctx.voice.aclose()
            await ctx.memory.stop()

    app = FastAPI(title="Mochi Server", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=(
            r"^(https?://(localhost|127\.0\.0\.1|tauri\.localhost)(:\d+)?|tauri://localhost)$"
        ),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.ctx = ctx
    app.state.manager = manager

    def require_token(request: Request) -> None:
        if not is_authorized(request, cfg.server_token):
            raise HTTPException(status_code=401, detail=ErrorCode.AUTH_FAILED.value)

    @app.get("/health")
    async def health() -> dict[str, object]:
        """健康检查：Tauri 边车探活与前端状态灯都依赖它。"""
        return {
            "status": "ok",
            "version": __version__,
            "protocol": PROTOCOL_VERSION,
            "uptime_s": round(time.time() - ctx.started_at, 3),
            "connections": manager.count,
            "emotion": ctx.emotion.state.label,
            "voice": {
                "tts": ctx.voice.enabled,
                "asr": cfg.asr_enabled,
                "mode": cfg.voice_input_mode,
            },
        }

    @app.post("/api/v1/sys/shutdown", dependencies=[Depends(require_token)])
    async def shutdown() -> dict[str, str]:
        """优雅关闭：先落盘情绪，再让边车退出（Tauri 会在 2s 后强杀兜底）。"""
        ctx.emotion.persist()

        async def _exit() -> None:
            await asyncio.sleep(0.1)
            os._exit(0)

        asyncio.create_task(_exit())
        return {"status": "shutting_down"}

    @app.get("/api/v1/sys/info", dependencies=[Depends(require_token)])
    async def sys_info() -> dict[str, object]:
        return {
            "version": __version__,
            "protocol": PROTOCOL_VERSION,
            "character": cfg.character,
            "data_dir": str(cfg.data_dir),
            "llm_configured": bool(ctx.llm.config.api_key),
            "token_required": bool(cfg.server_token),
        }

    # 用户可改设置（settings.json）：窗口位置/置顶/穿透/自启（计划书 4.8）
    patchable_keys = {"window", "agent"}

    @app.get("/api/v1/config/user", dependencies=[Depends(require_token)])
    async def get_user_settings() -> dict[str, Any]:
        return ctx.user_settings.get_all()

    @app.patch("/api/v1/config/user", dependencies=[Depends(require_token)])
    async def patch_user_settings(updates: dict[str, Any]) -> dict[str, Any]:
        unknown = set(updates) - patchable_keys
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown keys: {sorted(unknown)}")
        return ctx.user_settings.patch(updates)

    # ── LLM 配置（界面可改，即时生效）──
    @app.get("/api/v1/config/llm", dependencies=[Depends(require_token)])
    async def get_llm_config() -> dict[str, Any]:
        return _llm_view(ctx.llm.config)

    @app.patch("/api/v1/config/llm", dependencies=[Depends(require_token)])
    async def patch_llm_config(patch: LLMConfigPatch) -> dict[str, Any]:
        base_url = patch.base_url.strip() if patch.base_url is not None else None
        if base_url is not None:
            parsed = urlparse(base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise HTTPException(status_code=400, detail="base_url 必须是 http(s)://host 形式")
            base_url = base_url.rstrip("/")

        api_key = patch.api_key.strip() if patch.api_key is not None else None
        if api_key is not None and not api_key:
            raise HTTPException(status_code=400, detail="api_key 不能为空")

        model = patch.model.strip() if patch.model is not None else None
        config = await ctx.llm.update(
            base_url=base_url,
            api_key=api_key,
            model=model or None,
            disable_thinking=patch.disable_thinking,
        )
        return _llm_view(config)

    @app.get("/api/v1/llm/models", dependencies=[Depends(require_token)])
    async def list_llm_models() -> dict[str, Any]:
        try:
            models = await ctx.llm.list_models()
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=f"{exc.code}: {exc.detail}") from exc
        return {
            "models": models,
            "count": len(models),
            "base_url": ctx.llm.config.base_url,
        }

    # ── Live2D 衣柜：可用模型清单 ──
    @app.get("/api/v1/live2d/models", dependencies=[Depends(require_token)])
    async def list_live2d_models() -> dict[str, Any]:
        models = scan_live2d_models(cfg.data_dir / "live2d")
        return {"models": models, "count": len(models)}

    # ── 角色卡 × 模型交叉校验（T2-13）──
    @app.get("/api/v1/live2d/binding", dependencies=[Depends(require_token)])
    async def live2d_binding() -> dict[str, Any]:
        models = scan_live2d_models(cfg.data_dir / "live2d")
        report = validate_binding(ctx.characters.current, models)
        return report.to_payload()

    # ── 情感引擎调试 API（T3-01 / T3-18）──
    # ── 记忆 / 工具 / 技能（S6）──
    @app.get("/api/v1/characters", dependencies=[Depends(require_token)])
    async def list_characters() -> dict[str, Any]:
        items = []
        for card_id in ctx.characters.list_ids():
            try:
                card = CardLoader(ctx.characters.directory, card_id).current
                items.append({"id": card.id, "name": card.name, "greeting": card.greeting})
            except Exception:  # noqa: BLE001 - 坏卡不拖垮列表
                continue
        return {"characters": items, "current": ctx.characters.current.id}

    @app.post("/api/v1/characters/{card_id}/select", dependencies=[Depends(require_token)])
    async def select_character(card_id: str) -> dict[str, Any]:
        try:
            card = ctx.orchestrator.select_character(card_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"id": card.id, "name": card.name, "greeting": card.greeting}

    @app.get("/api/v1/logs", dependencies=[Depends(require_token)])
    async def tail_logs(lines: int = 200) -> dict[str, Any]:
        path = cfg.data_dir / "logs" / "mochi.log"
        if not path.exists():
            return {"lines": [], "path": str(path)}
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"lines": content[-max(1, min(lines, 2000)) :], "path": str(path)}

    @app.get("/api/v1/memory/sessions", dependencies=[Depends(require_token)])
    async def memory_sessions() -> dict[str, Any]:
        sessions = await ctx.memory.list_sessions()
        return {
            "sessions": [item.__dict__ for item in sessions],
            "current": ctx.memory.current_session,
        }

    @app.post("/api/v1/memory/sessions", dependencies=[Depends(require_token)])
    async def create_memory_session(body: MemorySessionRequest) -> dict[str, Any]:
        session_id = await ctx.memory.create_session(body.title)
        return {"id": session_id}

    @app.post("/api/v1/memory/sessions/{session_id}/switch", dependencies=[Depends(require_token)])
    async def switch_memory_session(session_id: str) -> dict[str, Any]:
        ok = await ctx.memory.switch_session(session_id)
        if not ok:
            raise HTTPException(status_code=404, detail="session not found")
        return {"current": ctx.memory.current_session}

    @app.patch("/api/v1/memory/sessions/{session_id}", dependencies=[Depends(require_token)])
    async def rename_memory_session(session_id: str, body: MemorySessionRequest) -> dict[str, Any]:
        if body.title:
            if ctx.memory.current_session != session_id:
                await ctx.memory.switch_session(session_id)
            await ctx.memory.rename_session(body.title)
        return {"ok": True}

    @app.delete("/api/v1/memory/sessions/{session_id}", dependencies=[Depends(require_token)])
    async def delete_memory_session(session_id: str) -> dict[str, Any]:
        await ctx.memory.delete_session(session_id)
        return {"ok": True, "current": ctx.memory.current_session}

    @app.get("/api/v1/memory/memories", dependencies=[Depends(require_token)])
    async def memory_list(limit: int = 100) -> dict[str, Any]:
        return {
            "memories": await ctx.memory.list_memories(max(1, min(limit, 500))),
            "profile": await ctx.memory.get_profile(),
        }

    @app.delete("/api/v1/memory/memories/{memory_id}", dependencies=[Depends(require_token)])
    async def memory_delete(memory_id: int) -> dict[str, Any]:
        await ctx.memory.delete_memory(memory_id)
        return {"ok": True}

    @app.post("/api/v1/memory/forget", dependencies=[Depends(require_token)])
    async def memory_forget() -> dict[str, Any]:
        await ctx.memory.forget(all_sessions=True)
        return {"ok": True}

    @app.get("/api/v1/tools", dependencies=[Depends(require_token)])
    async def list_tools() -> dict[str, Any]:
        return {"tools": ctx.tools.describe()}

    @app.post("/api/v1/tools/{name}/toggle", dependencies=[Depends(require_token)])
    async def toggle_tool(name: str, enabled: bool = True) -> dict[str, Any]:
        if not ctx.tools.set_enabled(name, enabled):
            raise HTTPException(status_code=404, detail="tool not found")
        return {"name": name, "enabled": enabled}

    @app.get("/api/v1/skills", dependencies=[Depends(require_token)])
    async def list_skills() -> dict[str, Any]:
        return {
            "skills": [
                {"name": item.name, "description": item.description}
                for item in ctx.skills.list_skills()
            ],
            "active": ctx.skills.active_names(),
        }

    @app.patch("/api/v1/config/agent", dependencies=[Depends(require_token)])
    async def patch_agent_config(body: AgentConfigPatch) -> dict[str, Any]:
        if body.route_mode is not None:
            ctx.orchestrator.set_route_mode(body.route_mode)
            ctx.user_settings.patch({"agent": {"route_mode": body.route_mode}})
        return {"route_mode": ctx.orchestrator.route_mode}

    @app.get("/api/v1/emotion/state", dependencies=[Depends(require_token)])
    async def emotion_state() -> dict[str, Any]:
        return {
            "state": ctx.emotion.snapshot().to_payload(),
            "frozen": ctx.emotion.frozen,
            "character": ctx.characters.current.id,
        }

    @app.get("/api/v1/emotion/history", dependencies=[Depends(require_token)])
    async def emotion_history(limit: int = 600) -> dict[str, Any]:
        items = ctx.emotion.history(max(1, min(limit, 5000)))
        return {"history": items, "count": len(items)}

    @app.get("/api/v1/emotion/catalog", dependencies=[Depends(require_token)])
    async def emotion_catalog() -> dict[str, Any]:
        labels = load_label_catalog()
        stimuli = load_stimulus_catalog()
        transitions = load_transitions()
        return {
            "labels": [
                {
                    "name": label.name,
                    "pad": {
                        "valence": label.valence,
                        "arousal": label.arousal,
                        "dominance": label.dominance,
                    },
                    "radius": label.radius,
                    "tau": label.tau,
                    "tts": label.tts,
                    "style": list(label.style),
                }
                for label in labels.labels
            ],
            "high_intensity_labels": sorted(labels.high_intensity_labels),
            "stimuli": [
                {
                    "tag": item.tag,
                    "category": item.category,
                    "dval": item.dval,
                    "darousal": item.darousal,
                    "ddominance": item.ddominance,
                    "habituate": item.habituate,
                }
                for item in stimuli.defs.values()
            ],
            "persona": ctx.characters.current.persona.model_dump(mode="json"),
            "transitions": [
                {
                    "from": sorted(rule.sources),
                    "to": rule.target,
                    "guards": [str(guard.get("name", "")) for guard in rule.guards],
                }
                for rule in transitions.rules
            ],
            "blocked_direct": [list(pair) for pair in sorted(transitions.blocked_direct)],
        }

    @app.post("/api/v1/emotion/stimulus", dependencies=[Depends(require_token)])
    async def inject_stimulus(body: StimulusRequest) -> dict[str, Any]:
        definition = load_stimulus_catalog().get(body.tag)
        if definition is None:
            raise HTTPException(status_code=400, detail=f"unknown stimulus: {body.tag}")
        stimulus = Stimulus(
            source=StimulusSource.SYSTEM,
            tag=body.tag,
            magnitude=body.magnitude,
            dval=definition.dval,
            darousal=definition.darousal,
            ddominance=definition.ddominance,
            confidence=1.0,
            note="dev_panel",
        )
        snapshot = await ctx.emotion.apply_stimulus(
            stimulus,
            preferred_label=body.preferred_label or definition.label_override,
        )
        return snapshot.to_payload()

    @app.post("/api/v1/emotion/advance", dependencies=[Depends(require_token)])
    async def advance_emotion(body: AdvanceRequest) -> dict[str, Any]:
        snapshot = ctx.emotion.advance(body.seconds)
        return snapshot.to_payload()

    @app.patch("/api/v1/emotion/persona", dependencies=[Depends(require_token)])
    async def patch_persona(patch: PersonaPatch) -> dict[str, Any]:
        card = ctx.characters.current
        merged = card.persona.model_dump(mode="json")
        for key, value in patch.model_dump(exclude_none=True).items():
            merged[key] = value
        card.persona = Persona.model_validate(merged)
        ctx.emotion.set_card(card)
        return {"persona": card.persona.model_dump(mode="json")}

    @app.post("/api/v1/emotion/persona/save", dependencies=[Depends(require_token)])
    async def save_persona() -> dict[str, Any]:
        card = ctx.characters.current
        path = ctx.characters.directory / f"{card.id}.yaml"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"card not found: {card.id}")
        backup = path.with_suffix(".yaml.bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text(
            yaml.safe_dump(card.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return {"saved": str(path), "backup": str(backup)}

    @app.post("/api/v1/emotion/greeting/consume", dependencies=[Depends(require_token)])
    async def consume_greeting() -> dict[str, Any]:
        greeting = ctx.emotion.consume_greeting()
        return {"greeting": greeting, "text": _greeting_text(ctx, greeting)}

    @app.get("/api/v1/emotion/export", dependencies=[Depends(require_token)])
    async def export_emotion(limit: int = 1200) -> JSONResponse:
        payload = {
            "version": 1,
            "exported_at": time.time(),
            "character": ctx.characters.current.id,
            "persona": ctx.characters.current.persona.model_dump(mode="json"),
            "state": ctx.emotion.snapshot().to_payload(),
            "history": ctx.emotion.history(max(1, min(limit, 5000))),
        }
        return JSONResponse(
            content=payload,
            headers={"Content-Disposition": 'attachment; filename="mochi-emotion-trace.json"'},
        )

    app.include_router(
        create_ws_router(
            cfg,
            manager,
            __version__,
            ctx.orchestrator,
            emotion=ctx.emotion,
            voice=ctx.voice,
            confirmations=ctx.confirmations,
        )
    )

    # Live2D 模型静态资源（本地存放，不入库；前端经 Vite proxy 同源访问）
    live2d_dir = cfg.data_dir / "live2d"
    if live2d_dir.exists():
        app.mount("/live2d", StaticFiles(directory=str(live2d_dir)), name="live2d")
        log.info("live2d static mounted: %s", live2d_dir)
    return app


def _greeting_text(ctx: AppContext, greeting: str | None) -> str | None:
    if greeting is None:
        return None
    lines = ctx.characters.current.persona.greetings
    return lines.get(greeting) or lines.get("long_absence") or ctx.characters.current.greeting
