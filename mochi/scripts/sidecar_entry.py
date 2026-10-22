"""PyInstaller 边车入口：只启动 FastAPI，不依赖仓库工作目录。"""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        frozen_dir = sys.__dict__.get("_MEIPASS")
        if frozen_dir:
            return Path(str(frozen_dir))
    return Path(__file__).resolve().parents[1]


def main() -> None:
    multiprocessing.freeze_support()
    base = _base_dir()
    server_dir = base / "server"
    if server_dir.is_dir():
        sys.path.insert(0, str(server_dir))

    cards = base / "characters"
    if cards.is_dir():
        os.environ.setdefault("CHARACTERS_DIR", str(cards))
    skills = base / "skills"
    if skills.is_dir():
        os.environ.setdefault("SKILLS_DIR", str(skills))
    os.environ.setdefault("SERVER_HOST", "127.0.0.1")

    import uvicorn

    from app.main import create_app

    settings_port = int(os.environ.get("SERVER_PORT", "8765"))
    uvicorn.run(
        create_app(),
        host=os.environ.get("SERVER_HOST", "127.0.0.1"),
        port=settings_port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
