"""Recolor the crimson-on-white lion into white-on-transparent for the crimson
header band. Run once: python scripts/make_lion_white.py"""
from pathlib import Path

from PIL import Image

SRC = Path("app/static/reports/lion.png")
DST = Path("app/static/reports/lion-white.png")


def main() -> None:
    im = Image.open(SRC).convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            # Near-white background -> transparent; everything else -> white,
            # keeping the original alpha as the shape mask.
            if r > 235 and g > 235 and b > 235:
                px[x, y] = (255, 255, 255, 0)
            else:
                px[x, y] = (255, 255, 255, a)
    im.save(DST)
    print(f"wrote {DST} ({im.size})")


if __name__ == "__main__":
    main()
