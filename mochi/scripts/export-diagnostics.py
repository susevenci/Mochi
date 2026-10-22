"""导出诊断包（T7-07）：日志 + 版本 + 脱敏配置，不包含 API Key。"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app import __version__  # noqa: E402
from app.config.settings import Settings  # noqa: E402


def mask(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    if len(value) <= 8:
        return "••••"
    return f"{value[:2]}••••{value[-4:]}"


def sanitize(data: object) -> object:
    if isinstance(data, dict):
        out: dict[object, object] = {}
        for key, value in data.items():
            lowered = str(key).lower()
            out[key] = "••••" if "key" in lowered or "token" in lowered else sanitize(value)
        return out
    if isinstance(data, list):
        return [sanitize(item) for item in data]
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 Mochi 诊断包")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    settings = Settings()
    data_dir = args.data_dir or settings.data_dir
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output = args.output or (ROOT.parent / "docs" / "evidence" / f"diagnostics-{timestamp}.zip")
    output.parent.mkdir(parents=True, exist_ok=True)

    info = {
        "version": __version__,
        "platform": platform.platform(),
        "python": sys.version,
        "data_dir": str(data_dir),
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("info.json", json.dumps(info, ensure_ascii=False, indent=2))
        log_dir = data_dir / "logs"
        if log_dir.is_dir():
            for path in sorted(log_dir.glob("mochi.log*")):
                archive.write(path, f"logs/{path.name}")
        settings_file = data_dir / "settings.json"
        if settings_file.is_file():
            try:
                payload = json.loads(settings_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {"raw": settings_file.read_text(encoding="utf-8", errors="replace")}
            archive.writestr(
                "settings.sanitized.json",
                json.dumps(sanitize(payload), ensure_ascii=False, indent=2),
            )
        archive.writestr("README.txt", "Mochi 诊断包：已脱敏，不包含 API Key / token。\n")
    print(f"diagnostics -> {output} ({output.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
