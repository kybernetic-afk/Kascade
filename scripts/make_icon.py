"""Generate assets/icon.ico for Kascade.

A rounded-square violet gradient with a white 'C' monogram. Build-time tool;
Pillow is only needed to regenerate the icon, not to run the app.

Usage:  python scripts/make_icon.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
TOP = (66, 230, 149)     # brand green #42E695
BOTTOM = (59, 178, 184)  # brand teal  #3BB2B8
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico")


def _gradient(size):
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = round(TOP[0] + (BOTTOM[0] - TOP[0]) * t)
        g = round(TOP[1] + (BOTTOM[1] - TOP[1]) * t)
        b = round(TOP[2] + (BOTTOM[2] - TOP[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img


def _font(size):
    for name in ("arialbd.ttf", "seguisb.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build():
    base = _gradient(SIZE).convert("RGBA")

    # Rounded-corner alpha mask
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=56, fill=255)
    base.putalpha(mask)

    draw = ImageDraw.Draw(base)
    font = _font(170)
    text = "K"
    box = draw.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    x = (SIZE - tw) / 2 - box[0]
    y = (SIZE - th) / 2 - box[1]
    draw.text((x, y), text, font=font, fill=(4, 42, 55, 255))  # brand deep teal

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    base.save(OUT, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Wrote", OUT)


if __name__ == "__main__":
    build()
