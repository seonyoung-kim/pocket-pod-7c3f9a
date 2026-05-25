"""Generate a 1400x1400 podcast cover image (iTunes compatible).

Usage:
    pip install Pillow
    python scripts/gen_cover.py [output-path]

기본 output: 프로젝트 루트의 cover.png
K가 자기 디자인으로 교체하고 싶으면 그냥 cover.png를 덮어쓰면 됨.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:
    sys.exit("Pillow가 필요합니다: pip install Pillow")


SIZE = 1400
BG_TOP    = (24, 24, 34)
BG_BOTTOM = (76, 56, 124)
ACCENT    = (255, 211, 102)   # 따뜻한 노랑
WHITE     = (245, 245, 250)
SUBTLE    = (200, 200, 215)

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNS.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient_bg(img: Image.Image) -> None:
    px = img.load()
    for y in range(SIZE):
        t = y / (SIZE - 1)
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        for x in range(SIZE):
            px[x, y] = (r, g, b)


def _draw_text_centered(draw: ImageDraw.ImageDraw, text: str,
                        cy: int, font: ImageFont.FreeTypeFont,
                        fill) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (SIZE - w) // 2 - bbox[0]
    y = cy - h // 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=fill)


def make_cover(out: Path) -> None:
    img = Image.new("RGB", (SIZE, SIZE), BG_TOP)
    _gradient_bg(img)
    draw = ImageDraw.Draw(img)

    # 가운데 큰 원형 강조 (마이크/방송 느낌)
    cx, cy = SIZE // 2, int(SIZE * 0.42)
    r_outer = 220
    draw.ellipse((cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
                  outline=ACCENT, width=10)
    r_inner = 70
    draw.ellipse((cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner),
                  fill=ACCENT)

    title_font = _load_font(180)
    sub_font   = _load_font(60)
    _draw_text_centered(draw, "pocket-pod", int(SIZE * 0.75),
                         title_font, WHITE)
    _draw_text_centered(draw, "personal LAN podcast", int(SIZE * 0.86),
                         sub_font, SUBTLE)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    print(f"wrote: {out} ({out.stat().st_size // 1024} KB)")


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cover.png")
    make_cover(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
