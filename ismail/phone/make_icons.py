"""The phone page's install icons: Chrome on Android installs a page as an app only with PNG icons (192 and 512 px,
and a maskable one for the round launcher mask). They redraw page/icon.svg (the ON AIR dot and four level bars on the
ground colour); run this after changing that mark.

    python -m ismail.phone.make_icons
"""
import colorsys
from pathlib import Path

from PIL import Image, ImageDraw

PAGE = Path(__file__).parent / 'page'
GROUND, FRAME, AIR = (14, 13, 11), (44, 42, 37), (255, 75, 62)
ACCENT = tuple(round(c * 255) for c in colorsys.hls_to_rgb(293 / 360, 0.66, 0.68))   # hsl(293 68% 66%)
SS = 4                                                                                # supersampling


def mark(size, safe=1.0, rounded=True):
    """The mark at `size` px; safe < 1 shrinks it into the maskable safe zone on a full-bleed ground."""
    n = size * SS
    im = Image.new('RGB', (n, n), GROUND)
    d = ImageDraw.Draw(im)
    if rounded:                                      # the corners outside the rounded ground are transparent
        im = Image.new('RGBA', (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, n - 1, n - 1], radius=24 * n / 512, fill=GROUND)
    k = n / 512 * safe
    o = n * (1 - safe) / 2
    p = lambda v: o + v * k                                                           # noqa: E731
    d.rounded_rectangle([p(96), p(96), p(416), p(416)], radius=12 * k, outline=FRAME, width=round(16 * k))
    d.ellipse([p(160 - 22), p(160 - 22), p(160 + 22), p(160 + 22)], fill=AIR)
    for x, top in ((168, 304), (232, 240), (296, 272), (360, 208)):
        d.rectangle([p(x - 13), p(top), p(x + 13), p(368)], fill=ACCENT)
    return im.resize((size, size), Image.LANCZOS)


def main():
    mark(192).save(PAGE / 'icon-192.png', optimize=True)
    mark(512).save(PAGE / 'icon-512.png', optimize=True)
    mark(512, safe=0.8, rounded=False).save(PAGE / 'icon-maskable.png', optimize=True)
    mark(180, rounded=False).save(PAGE / 'apple-touch-icon.png', optimize=True)
    print('wrote', ', '.join(p.name for p in sorted(PAGE.glob('*.png'))))


if __name__ == '__main__':
    main()
