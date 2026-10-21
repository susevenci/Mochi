"""生成"静态立绘兜底"用的 PNG（不依赖 Pillow，纯标准库）。

用途：模型加载失败时前端显示一张静态立绘 + 情绪驱动的 CSS 滤镜，
而不是白屏或占位圆（计划书 5.6.7 的兜底要求）。

用法：``python scripts/make_fallback_portrait.py``
产出：``frontend/public/fallback/portrait.png``（512x512 RGBA，透明背景）
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SIZE = 512
SUPERSAMPLE = 3  # 每像素 3x3 采样，边缘不至于锯齿

OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "fallback" / "portrait.png"

# 配色：柔和的粉发 + 深色眼，方便用 CSS filter 做情绪染色
HAIR = (246, 200, 208)
HAIR_SHADE = (226, 172, 184)
SKIN = (255, 236, 232)
SKIN_SHADE = (247, 216, 210)
EYE = (60, 44, 52)
BLUSH = (250, 178, 186)
MOUTH = (206, 118, 130)
CLOTHES = (168, 194, 240)
OUTLINE = (150, 110, 122)


def ellipse(x: float, y: float, cx: float, cy: float, rx: float, ry: float) -> bool:
    if rx <= 0 or ry <= 0:
        return False
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def rounded_body(x: float, y: float) -> bool:
    """身体：上窄下宽的圆角梯形。"""
    if not 300 <= y <= 500:
        return False
    t = (y - 300) / 200
    half = 70 + 95 * t
    return abs(x - 256) <= half


def sample_rgba(x: float, y: float) -> tuple[int, int, int, int]:
    """返回该点的颜色（含 alpha）。用"从后往前"的绘制顺序叠加层。"""
    color: tuple[int, int, int, int] | None = None

    # ① 后层：头发（大圆）与双马尾
    if ellipse(x, y, 256, 206, 152, 164):
        color = (*HAIR, 255)
    for cx in (96.0, 416.0):
        if ellipse(x, y, cx, 260, 46, 108):
            color = (*HAIR_SHADE, 255)

    # ② 身体（衣服）
    if rounded_body(x, y):
        color = (*CLOTHES, 255)
    # ③ 脖子
    elif 292 <= y <= 334 and abs(x - 256) <= 32:
        color = (*SKIN_SHADE, 255)

    # ④ 脸（盖住后发，再在脸上画刘海与五官）
    if ellipse(x, y, 256, 240, 112, 118):
        color = (*SKIN, 255)
        bang_bottom = 208 + 10 * math.sin((x - 256) / 24)
        if y < bang_bottom:
            color = (*HAIR, 255)
        else:
            if ellipse(x, y, 214, 258, 20, 24) or ellipse(x, y, 298, 258, 20, 24):
                color = (*EYE, 255) if ellipse(x, y, 214, 262, 11, 15) or ellipse(
                    x, y, 298, 262, 11, 15
                ) else (255, 255, 255, 255)
            elif ellipse(x, y, 190, 296, 18, 9) or ellipse(x, y, 322, 296, 18, 9):
                color = (*BLUSH, 200)
            elif ellipse(x, y, 256, 312, 11, 5) and y >= 312:
                color = (*MOUTH, 255)

    return color if color is not None else (0, 0, 0, 0)


def outline_pass(x: float, y: float, base: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """在透明边缘画一圈描边，看起来像正经立绘而不是色块。"""
    if base[3] == 255:
        return base
    for dx, dy in ((1.6, 0), (-1.6, 0), (0, 1.6), (0, -1.6)):
        if sample_rgba(x + dx, y + dy)[3] == 255:
            return (*OUTLINE, 255)
    return base


def build_rows() -> list[bytes]:
    rows: list[bytes] = []
    step = 1.0 / SUPERSAMPLE
    weight = 1 / (SUPERSAMPLE * SUPERSAMPLE)
    for py in range(SIZE):
        row = bytearray()
        for px in range(SIZE):
            r = g = b = a = 0.0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    x = px + (sx + 0.5) * step
                    y = py + (sy + 0.5) * step
                    cr, cg, cb, ca = outline_pass(x, y, sample_rgba(x, y))
                    if ca == 0:
                        continue
                    alpha = ca / 255
                    r += cr * alpha * weight
                    g += cg * alpha * weight
                    b += cb * alpha * weight
                    a += alpha * weight
            if a <= 0.004:
                row += b"\x00\x00\x00\x00"
                continue
            row += bytes(
                (
                    min(255, round(r / a)),
                    min(255, round(g / a)),
                    min(255, round(b / a)),
                    min(255, round(a * 255)),
                )
            )
        rows.append(bytes(row))
    return rows


def write_png(path: Path, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    rows = build_rows()
    write_png(OUT, rows)
    print(f"written {OUT} ({OUT.stat().st_size / 1024:.1f} KB) size={SIZE}x{SIZE}")
    # 顺带验证 PNG 结构头
    assert OUT.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert math.isclose(OUT.stat().st_size, OUT.stat().st_size)


if __name__ == "__main__":
    main()
