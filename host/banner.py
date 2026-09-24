"""Render a message into the 1-bit banner bitmap the board displays.

The panel has no CJK font of its own, so the PC rasterises the text and ships
the resulting bitmap as one base64 line:

    B,<x>,<y>,<w>,<h>,<duration_ms>,<base64>

Bit convention matches U8g2's ``drawXBM``: bits are LSB-first within each byte,
rows are padded to a whole byte, and a set bit means **ink**.  The firmware
paints the rectangle with the paper colour first, so zeros in this bitmap read
as blank background.
"""

from __future__ import annotations

import base64
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = None

# Must match host-side defaults used by the GUI / engine.
BANNER_W = 384
BANNER_H = 64
BANNER_X = 8
BANNER_Y = 228

# Text layout, in pixels.  h must fit TOP + TITLE_LINE + 2 * BODY_LINE + a
# little slack, which is what BANNER_H above is sized for.
PAD_X = 10
TOP = 6
TITLE_SIZE = 16
BODY_SIZE = 12
TITLE_LINE = 20
BODY_LINE = 15

# Candidate fonts, most preferred first.  The first two ship with Windows and
# cover Chinese; the rest are fallbacks for other systems.
_TITLE_FONTS = ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "simsun.ttc",
                "dejavusans-bold.ttf", "arialbd.ttf", "arial.ttf")
_BODY_FONTS = ("msyh.ttc", "simhei.ttf", "simsun.ttc",
               "dejavusans.ttf", "arial.ttf")
_FONT_DIRS = (
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    "/usr/share/fonts/truetype/dejavu",
    "/System/Library/Fonts",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts"),
)


def available() -> bool:
    return Image is not None


def _find_font(names) -> str | None:
    for name in names:
        for d in _FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None


def _load_font(names, size: int):
    path = _find_font(names)
    try:
        if path:
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x2E80 <= o <= 0x9FFF) or (0xF900 <= o <= 0xFAFF) or \
           (0xFF00 <= o <= 0xFF60) or (0x3000 <= o <= 0x303F)


def _tokens(text: str):
    """Split into wrappable units: single CJK chars, whole Latin words."""
    out = []
    buf = ""
    for ch in text:
        if _is_cjk(ch) or ch.isspace():
            if buf:
                out.append(buf)
                buf = ""
            if not ch.isspace():
                out.append(ch)
        else:
            buf += ch
    if buf:
        out.append(buf)
    return out


def _wrap(draw, text: str, font, max_w: float, max_lines: int):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for tok in _tokens(para):
            candidate = cur + tok if (cur.endswith(" ") or not cur) else cur + " " + tok
            if draw.textlength(candidate, font=font) <= max_w or not cur:
                cur = candidate
            else:
                lines.append(cur)
                cur = tok
                if len(lines) >= max_lines:
                    break
        if len(lines) >= max_lines:
            break
        lines.append(cur)
    lines = [ln.strip() for ln in lines[:max_lines]]
    while lines and not lines[-1]:
        lines.pop()
    return lines or [""]


def _ellipsise(draw, text: str, font, max_w: float) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def render(title: str, body: str = "", w: int = BANNER_W, h: int = BANNER_H):
    """Return a greyscale PIL image (255 = paper, 0 = ink) for the message."""
    if Image is None:
        raise RuntimeError("Pillow is required to render banners")

    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)

    # outer border, drawn as ink
    d.rectangle([0, 0, w - 1, h - 1], outline=0, width=2)

    inner_w = w - 2 * PAD_X
    title = (title or "").strip()
    body = (body or "").strip()

    f_title = _load_font(_TITLE_FONTS, TITLE_SIZE)
    f_body = _load_font(_BODY_FONTS, BODY_SIZE)

    if title and body:
        # Title on its own line, body wrapped underneath -- laid out top-down so
        # a long message can never collide with the bottom border.
        title = _ellipsise(d, title.replace("\n", " "), f_title, inner_w)
        lines = _wrap(d, body, f_body, inner_w, 2)
        y = TOP
        d.text((PAD_X, y), title, font=f_title, fill=0, anchor="la")
        y += TITLE_LINE
        for ln in lines:
            d.text((PAD_X, y), ln, font=f_body, fill=0, anchor="la")
            y += BODY_LINE
        return img

    # Only one piece of text: give it the whole box, centred.
    text = title or body
    lines = _wrap(d, text, f_title, inner_w, 2)
    lines = [_ellipsise(d, ln, f_title, inner_w) for ln in lines]
    total = TITLE_LINE * len(lines)
    y = (h - total) / 2
    for ln in lines:
        d.text((PAD_X, y), ln, font=f_title, fill=0, anchor="la")
        y += TITLE_LINE
    return img


def pack_xbm(img) -> bytes:
    """Pack a greyscale image into the XBM bit layout drawXBM() expects."""
    w, h = img.size
    px = img.load()
    stride = (w + 7) // 8
    out = bytearray(stride * h)
    for y in range(h):
        row = y * stride
        for x in range(w):
            if px[x, y] < 128:
                out[row + (x >> 3)] |= 1 << (x & 7)
    return bytes(out)


def encode(title: str, body: str = "", w: int = BANNER_W, h: int = BANNER_H,
           x: int = BANNER_X, y: int = BANNER_Y, duration_ms: int = 8000) -> str:
    """Full protocol line that shows `title`/`body` on the board."""
    bits = pack_xbm(render(title, body, w, h))
    return "B,%d,%d,%d,%d,%d,%s" % (
        x, y, w, h, int(duration_ms), base64.b64encode(bits).decode("ascii"))


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="preview a banner")
    ap.add_argument("title", nargs="?", default="该喝水啦")
    ap.add_argument("body", nargs="?", default="已经坐了 45 分钟，站起来活动一下")
    ap.add_argument("--out", default=os.path.join(os.environ.get("TEMP", "."),
                                                  "banner_preview.png"))
    args = ap.parse_args()
    img = render(args.title, args.body)
    img.save(args.out)
    line = encode(args.title, args.body)
    print("wrote %s  (%dx%d, protocol line %d chars)"
          % (args.out, BANNER_W, BANNER_H, len(line)))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
