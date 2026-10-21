"""把 data/preview/*.png 压成 640px 的白底 JPG 缩略图，便于快速预览。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

PREVIEW = Path(__file__).resolve().parents[1] / "data" / "preview"


def main() -> int:
    for src in sorted(PREVIEW.glob("*.png")):
        if src.name.startswith("thumb-"):
            continue
        with Image.open(src) as image:
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            merged = Image.alpha_composite(background, rgba).convert("RGB")
            merged.thumbnail((640, 640))
            out = PREVIEW / f"thumb-{src.stem}.jpg"
            merged.save(out, "JPEG", quality=88)
            print(f"{out.name} {merged.size[0]}x{merged.size[1]} {out.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
