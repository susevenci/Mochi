"""服务入口：FastAPI 应用装配、健康检查、REST 与 WS 挂载。

开发：``python -m uvicorn --app-dir server app.main:create_app --factory --reload``
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .bootstrap import bootstrap
from .config.llm_settings import LLMConfig, mask_key
from .config.settings import Settings
from .context import AppContext
from .gateway.auth import is_authorized
from .gateway.errors import ErrorCode
from .gateway.protocol import PROTOCOL_VERSION
from .gateway.ws import ConnectionManager, create_ws_router
from .providers.base import LLMError

log = logging.getLogger(__name__)


class LLMConfigPatch(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    disable_thinking: bool | None = None


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
    """扫描 data/live2d/<目录>/<目录>.model3.json，返回模型能力清单（衣柜）。"""
    models: list[dict[str, Any]] = []
    if not root.exists():
        return models
    for model_json in sorted(root.glob("*/*.model3.json")):
        try:
            data = json.loads(model_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        refs = data.get("FileReferences") or {}
        motions = sum(len(group or []) for group in (refs.get("Motions") or {}).values())
        expressions = len(refs.get("Expressions") or [])
        folder = model_json.parent.name
        models.append(
            {
                "id": folder,
                "name": str(data.get("Name") or folder),
                "url": f"/live2d/{folder}/{model_json.name}",
                "motions": motions,
                "expressions": expressions,
            }
        )
    return models


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    ctx: AppContext = bootstrap(cfg)
    manager = ConnectionManager()

    app = FastAPI(title="Mochi Server", version=__version__)
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
        }

    @app.get("/api/v1/sys/info", dependencies=[Depends(require_token)])
    async def sys_info() -> dict[str, object]:
        return {
            "version": __version__,
            "protocol": PROTOCOL_VERSION,
            "character": cfg.character,
            "data_dir": str(cfg.data_dir),
            "llm_configured": bool(cfg.llm_api_key),
            "token_required": bool(cfg.server_token),
        }

    # 用户可改设置（settings.json）：窗口位置/置顶/穿透/自启（计划书 4.8）
    patchable_keys = {"window"}

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
                raise HTTPException(
                    status_code=400, detail="base_url 必须是 http(s)://host 形式"
                )
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

    app.include_router(create_ws_router(cfg, manager, __version__, ctx.orchestrator))

    # Live2D 模型静态资源（本地存放，不入库；前端经 Vite proxy 同源访问）
    live2d_dir = cfg.data_dir / "live2d"
    if live2d_dir.exists():
        app.mount("/live2d", StaticFiles(directory=str(live2d_dir)), name="live2d")
        log.info("live2d static mounted: %s", live2d_dir)
    return app
