"""Live2D 模型选型辅助（Eikanya/Live2d-model 仓库）。

用法：
    python scripts/live2d_pick.py list                        # 根目录（游戏合集）
    python scripts/live2d_pick.py files 碧蓝航线,Azue          # 逐级浏览（逗号分隔，模糊匹配）
    python scripts/live2d_pick.py files 碧蓝航线,Azue,企业      # 再进一层看角色文件
    python scripts/live2d_pick.py preview 碧蓝航线,Azue,企业 ent.png   # 下载贴图当预览

注意：GitHub 未认证 API 限速 60 次/小时，脚本对根目录做了缓存。
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import quote

API = "https://api.github.com/repos/Eikanya/Live2d-model/contents/"
RAW = "https://raw.githubusercontent.com/Eikanya/Live2d-model/master/"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "preview"
UA = {"User-Agent": "mochi-live2d-picker"}

_cache: dict[str, list[dict]] = {}


def _entries(path: str = "") -> list[dict]:
    if path in _cache:
        return _cache[path]
    url = API + quote(path, safe="/") if path else API
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    result = data if isinstance(data, list) else []
    _cache[path] = result
    return result


def _resolve_path(spec: str) -> str:
    current = ""
    for part in [chunk.strip() for chunk in spec.split(",") if chunk.strip()]:
        match = next(
            (
                str(item["name"])
                for item in _entries(current)
                if item["type"] == "dir" and part.lower() in str(item["name"]).lower()
            ),
            None,
        )
        if match is None:
            available = ", ".join(
                str(item["name"]) for item in _entries(current) if item["type"] == "dir"
            )
            raise SystemExit(f"未找到: {part}\n当前层可选: {available or '（无子目录）'}")
        current = f"{current}/{match}" if current else match
    return current


def cmd_list() -> int:
    dirs = sorted(str(item["name"]) for item in _entries("") if item["type"] == "dir")
    print(f"{len(dirs)} 个合集")
    for name in dirs:
        print(" ", name)
    return 0


def _download_json(url: str) -> dict:
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def cmd_inspect(spec: str) -> int:
    """读取模型的 model3.json，统计表情/动作/贴图——选型的关键依据。"""
    path = _resolve_path(spec)
    entries = _entries(path)
    model_rel = next(
        (
            str(item["name"])
            for item in entries
            if item["type"] == "file" and str(item["name"]).endswith((".model3.json", ".model.json"))
        ),
        None,
    )
    if model_rel is None:
        for sub in (item for item in entries if item["type"] == "dir"):
            rel_dir = str(sub["name"])
            found = next(
                (
                    f"{rel_dir}/{item['name']}"
                    for item in _entries(f"{path}/{rel_dir}")
                    if item["type"] == "file"
                    and str(item["name"]).endswith((".model3.json", ".model.json"))
                ),
                None,
            )
            if found:
                model_rel = found
                break
    if model_rel is None:
        print(f"{path}: 未找到 model 定义文件")
        return 1

    data = _download_json(RAW + quote(f"{path}/{model_rel}", safe="/"))
    refs = data.get("FileReferences") or {}
    expressions = refs.get("Expressions") or []
    motions = refs.get("Motions") or {}
    textures = refs.get("Textures") or []
    groups = data.get("Groups") or []

    motion_total = sum(len(items or []) for items in motions.values())
    print(f"# {path}")
    print(f"  model      : {model_rel}")
    print(f"  cubism     : {'3/4' if model_rel.endswith('.model3.json') else '2'}")
    print(f"  textures   : {len(textures)}")
    print(f"  physics    : {'yes' if refs.get('Physics') else 'no'}")
    print(f"  pose       : {'yes' if refs.get('Pose') else 'no'}")
    print(f"  expressions: {len(expressions)}")
    for expr in expressions:
        print(f"    - {expr.get('Name')}")
    print(f"  motions    : {motion_total}（{len(motions)} 组）")
    for name, items in motions.items():
        print(f"    - {name}: {len(items or [])}")
    hit_areas = next((g for g in groups if g.get("Name") == "HitAreas"), None)
    if hit_areas:
        print(f"  hit_areas  : {[i.get('Id') for i in hit_areas.get('Ids') or []]}")
    return 0


def cmd_files(spec: str) -> int:
    path = _resolve_path(spec)
    print(f"# path: {path}")
    for item in _entries(path):
        size = item.get("size") or ""
        print(f"  {item['type']:4} {item['name']} {size}")
    return 0


def cmd_preview(spec: str, out_name: str = "preview.png") -> int:
    path = _resolve_path(spec)
    print(f"# path: {path}")
    entries = _entries(path)

    candidates = [
        dict(item, rel=str(item["name"]))
        for item in entries
        if item["type"] == "file" and str(item["name"]).lower().endswith(".png")
    ]
    if not candidates:
        for sub in (item for item in entries if item["type"] == "dir"):
            rel_dir = str(sub["name"])
            for item in _entries(f"{path}/{rel_dir}"):
                if item["type"] == "file" and str(item["name"]).lower().endswith(".png"):
                    candidates.append(dict(item, rel=f"{rel_dir}/{item['name']}"))
            if candidates:
                break

    if not candidates:
        print("未找到 png 贴图")
        return 1

    def score(item: dict) -> tuple[int, int]:
        lowered = str(item["rel"]).lower()
        named = 1 if "texture" in lowered or "tex" in lowered else 0
        return (named, int(item.get("size") or 0))

    best = max(candidates, key=score)
    url = RAW + quote(f"{path}/{best['rel']}", safe="/")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / out_name
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=120) as response:
        target.write_bytes(response.read())
    print(f"saved {target} ({target.stat().st_size} bytes) from {best['rel']}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    command = sys.argv[1]
    if command == "list":
        return cmd_list()
    if command == "files" and len(sys.argv) >= 3:
        return cmd_files(sys.argv[2])
    if command == "inspect" and len(sys.argv) >= 3:
        return cmd_inspect(sys.argv[2])
    if command == "compare" and len(sys.argv) >= 3:
        for spec in [chunk for chunk in sys.argv[2].split("+") if chunk]:
            cmd_inspect(spec)
            print()
        return 0
    if command == "preview" and len(sys.argv) >= 3:
        out = sys.argv[3] if len(sys.argv) >= 4 else "preview.png"
        return cmd_preview(sys.argv[2], out)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
