"""构建 Python 边车（T5-01）：PyInstaller onefile，产物供 Tauri resource 使用。"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "sidecar"
WORK = ROOT / "build" / "sidecar"
TAURI_BIN = ROOT / "desktop" / "src-tauri" / "binaries" / "mochi-server.exe"


def build() -> Path:
    sep = ";" if sys.platform.startswith("win") else ":"
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "mochi-server",
        "--paths",
        str(ROOT / "server"),
        "--add-data",
        f"{ROOT / 'characters'}{sep}characters",
        "--add-data",
        f"{ROOT / 'server' / 'app' / 'emotion' / 'data'}{sep}app/emotion/data",
        "--collect-submodules",
        "app",
        "--collect-submodules",
        "uvicorn",
        "--hidden-import",
        "app.main",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(WORK),
        str(ROOT / "scripts" / "sidecar_entry.py"),
    ]
    print("[sidecar] " + " ".join(args))
    subprocess.run(args, cwd=str(ROOT), check=True)
    name = "mochi-server.exe" if sys.platform.startswith("win") else "mochi-server"
    produced = DIST / name
    if not produced.exists():
        raise SystemExit(f"sidecar not found: {produced}")
    TAURI_BIN.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(produced, TAURI_BIN)
    print(f"[sidecar] {produced} -> {TAURI_BIN} ({produced.stat().st_size / 1024 / 1024:.1f} MB)")
    return TAURI_BIN


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip", action="store_true", help="只检查已有产物")
    args = parser.parse_args()
    if args.skip:
        print(TAURI_BIN if TAURI_BIN.exists() else "missing")
        return 0 if TAURI_BIN.exists() else 1
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
