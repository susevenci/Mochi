"""服务入口：FastAPI 应用装配、健康检查、REST 与 WS 挂载。

开发：``python -m uvicorn --app-dir server app.main:create_app --factory --reload``
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request

from . import __version__
from .bootstrap import bootstrap
from .config.settings import Settings
from .context import AppContext
from .gateway.auth import is_authorized
from .gateway.errors import ErrorCode
from .gateway.protocol import PROTOCOL_VERSION
from .gateway.ws import ConnectionManager, create_ws_router

log = logging.getLogger(__name__)


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

    app.include_router(create_ws_router(cfg, manager, __version__, ctx.orchestrator))
    return app
