#!/usr/bin/env python3
"""Generate the bongo cat sprite frames from the original BongoCat artwork.

The cat art comes from https://github.com/ayangweb/BongoCat (MIT).  That app
draws a static ``background.png`` (desk + arrow keys + keyboard) and then a
Live2D model on top; ``tools/extract_source_art.py`` recovers the cat as a
plain RGBA layer by subtracting the two.

The Live2D model animates two parameters, ``CatParamLeftHandDown`` and
``CatParamRightHandDown``.  We reproduce that by sliding the corresponding paw
down behind the desk edge: the cat sits behind the desk, so anything below the
desk line is simply hidden.  Only the paw's own outline is moved, which keeps
the rest of the silhouette intact.

Usage::

    python tools/extract_source_art.py --repo BongoCat   # one-off, needs the clone
    python tools/make_art.py --preview docs/art_preview.png
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pngmini import over_white, read_rgba, write_gray  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(HERE, "assets")

SRC_W, SRC_H = 612, 354        # resolution of the upstream render
OUT_W, OUT_H = 400, 232        # scene size expected by the firmware

# How far a paw slides down (at source resolution) when it is "pressed".
PRESS_DY = 30

# How big the cat is drawn relative to the original render.  1.0 keeps the
# upstream proportions; lower it if the cat looks too large on the panel.
CAT_SCALE = 0.78
# Horizontal centre the cat is scaled about (the anchor's y is the desk edge).
CAT_ANCHOR_X = 330

# Regions of the cat layer that make up each paw's *own* outline.  They are
# deliberately tight: everything outside them (notably the body contour that
# the left paw's crown merges into) must stay put.
#   (x0, y0, x1, y1)   y1 = None  ->  down to the desk edge
PAW_REGIONS = {
    "left": [(118, 74, 160, None),      # outer wall
             (118, 74, 184, 96),        # crown, stopping short of the body
             (134, 100, 180, 180)],     # the pads
    "right": [(384, 130, 478, None)],   # the whole arch
}

# The eyes are two isolated dots; blinking squashes them, exactly like the
# upstream model does when ParamEyeLOpen is multiplied down.
EYES = [(252, 140), (371, 177)]         # (centre x, centre y)
EYE_RX, EYE_RY = 9, 9
BLINK_RY = 3

FRAMES = ["rest", "rest_blink", "left", "right", "both", "sleep"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def lum(r: int, g: int, b: int) -> int:
    return (r * 299 + g * 587 + b * 114) // 1000


def desk_line(desk_rgba) -> list[int]:
    """Topmost y of the thick dark desk edge, per column."""
    out = []
    for x in range(SRC_W):
        found = SRC_H
        for y in range(100, SRC_H - 2):
            o = (y * SRC_W + x) * 4
            if all(desk_rgba[((y + k) * SRC_W + x) * 4] < 90 for k in range(3)):
                found = y
                break
        out.append(found)
    return out


class Scene:
    """The flattened cat-over-desk scene, in luminance, plus a pose applier."""

    def __init__(self, desk_rgba, cat_rgba):
        # Flatten both layers onto white first: transparent pixels are stored
        # as (0,0,0,0) upstream, and sampling their RGB directly would paint
        # every transparent region solid black.
        n = SRC_W * SRC_H
        self.desk = over_white(desk_rgba, n)
        self.cat = over_white(cat_rgba, n)
        self.dl = desk_line(desk_rgba)
        self.solid = bytearray(n)
        self.pad = bytearray(n)
        for i in range(n):
            if not cat_rgba[i * 4 + 3]:
                continue
            self.solid[i] = 1
            o = i * 4
            r, g, b = cat_rgba[o], cat_rgba[o + 1], cat_rgba[o + 2]
            if r > 190 and g < 170 and b < 190 and r - g > 55:
                self.pad[i] = 1

        # The pads are painted pink upstream.  A monochrome panel has no spot
        # colour, so draw their silhouette as an outline instead of a blob.
        self.pad_edge = bytearray(n)
        for y in range(1, SRC_H - 1):
            for x in range(1, SRC_W - 1):
                i = y * SRC_W + x
                if not self.pad[i]:
                    continue
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if not self.pad[i + dy * SRC_W + dx]:
                            self.pad_edge[i] = 1
                            break
                    if self.pad_edge[i]:
                        break

    def desk_lum(self, i: int) -> int:
        o = i * 3
        return lum(self.desk[o], self.desk[o + 1], self.desk[o + 2])

    def cat_lum(self, i: int) -> int:
        """Cat colour for pixel `i`, with the pink pads converted to line art."""
        if self.pad_edge[i]:
            return 0
        if self.pad[i]:
            return 255
        o = i * 3
        return lum(self.cat[o], self.cat[o + 1], self.cat[o + 2])

    def base(self) -> bytearray:
        return bytearray(self.cat_lum(i) if self.solid[i] else self.desk_lum(i)
                         for i in range(SRC_W * SRC_H))

    # -- the cat as its own layer ------------------------------------------
    # Keeping the cat separate from the desk is what lets us resize it: the
    # desk, arrow keys and keyboard stay put while the cat shrinks.
    def cat_layer(self):
        """(luminance, mask) for the cat alone, as extracted."""
        n = SRC_W * SRC_H
        col = bytearray(n)
        mask = bytearray(n)
        for i in range(n):
            if self.solid[i]:
                mask[i] = 1
                col[i] = self.cat_lum(i)
        self._cat_col = col
        return col, mask

    # -- poses -------------------------------------------------------------
    def press(self, col: bytearray, mask: bytearray, which: str, dy: int) -> None:
        """Slide one paw down behind the desk edge."""
        cells = []
        for x0, y0, x1, y1 in PAW_REGIONS[which]:
            for x in range(x0, x1 + 1):
                bottom = self.dl[x] if y1 is None else min(y1, self.dl[x])
                cells.append((x, y0, bottom))
        for x, y0, y1 in cells:
            for y in range(y0, y1 + 1):
                mask[y * SRC_W + x] = 0            # lift the original out
        for x, y0, y1 in cells:
            for y in range(y0, y1 + 1):
                i = y * SRC_W + x
                if not self.solid[i]:
                    continue
                ny = y + dy
                if ny >= SRC_H or ny >= self.dl[x]:    # hidden by the desk
                    continue
                j = ny * SRC_W + x
                mask[j] = 1
                col[j] = self._cat_col[i]

    def blink(self, col: bytearray, mask: bytearray) -> None:
        for cx, cy in EYES:
            for y in range(cy - EYE_RY - 2, cy + EYE_RY + 3):
                for x in range(cx - EYE_RX - 2, cx + EYE_RX + 3):
                    if 0 <= x < SRC_W and 0 <= y < SRC_H:
                        mask[y * SRC_W + x] = 0
            for y in range(cy - BLINK_RY, cy + BLINK_RY + 1):
                for x in range(cx - EYE_RX, cx + EYE_RX + 1):
                    if 0 <= x < SRC_W and 0 <= y < SRC_H:
                        j = y * SRC_W + x
                        mask[j] = 1
                        col[j] = 0

    def scale_cat(self, col: bytearray, mask: bytearray, s: float):
        """Resize the cat about a point on the desk edge.

        Because the anchor lies exactly on the desk line, and scaling about a
        point on a line maps that line onto itself, the cat's bottom edge stays
        glued to the desk at any scale -- it never floats or sinks.
        """
        if abs(s - 1.0) < 1e-3:
            return col, mask

        ax = CAT_ANCHOR_X
        ay = self.dl[ax]
        inv = 1.0 / s
        n = SRC_W * SRC_H
        out_c = bytearray(n)
        out_m = bytearray(n)

        for oy in range(SRC_H):
            sy0 = ay + (oy - ay) * inv
            sy1 = ay + (oy + 1 - ay) * inv
            iy0 = max(0, int(sy0))
            iy1 = min(SRC_H, max(iy0 + 1, int(sy1 + 0.999)))
            for ox in range(SRC_W):
                sx0 = ax + (ox - ax) * inv
                sx1 = ax + (ox + 1 - ax) * inv
                ix0 = max(0, int(sx0))
                ix1 = min(SRC_W, max(ix0 + 1, int(sx1 + 0.999)))
                hit = 0
                darkest = 255
                for y in range(iy0, iy1):
                    base = y * SRC_W
                    for x in range(ix0, ix1):
                        i = base + x
                        if mask[i]:
                            hit = 1
                            if col[i] < darkest:
                                darkest = col[i]
                if hit:                      # any coverage keeps thin lines
                    j = oy * SRC_W + ox
                    out_m[j] = 1
                    out_c[j] = darkest
        return out_c, out_m

    def render(self, paws=(), blink=False, cat_scale=1.0) -> bytearray:
        col, mask = self.cat_layer()
        for which in paws:
            self.press(col, mask, which, PRESS_DY)
        if blink:
            self.blink(col, mask)
        col, mask = self.scale_cat(col, mask, cat_scale)

        out = bytearray(SRC_W * SRC_H)
        for y in range(SRC_H):
            base = y * SRC_W
            for x in range(SRC_W):
                i = base + x
                out[i] = (col[i] if (mask[i] and y < self.dl[x])
                          else self.desk_lum(i))
        return out

    def poses(self):
        return {
            "rest":       dict(),
            "rest_blink": dict(blink=True),
            "left":       dict(paws=("left",)),
            "right":      dict(paws=("right",)),
            "both":       dict(paws=("left", "right")),
            "sleep":      dict(paws=("left", "right"), blink=True),
        }


# ---------------------------------------------------------------------------
# down-sampling: 612x354 luminance -> 400x232 1-bit
# ---------------------------------------------------------------------------
def downscale(src: bytearray, thr: int = 150) -> list[bytearray]:
    rows = []
    for oy in range(OUT_H):
        y0 = oy * SRC_H // OUT_H
        y1 = max(y0 + 1, (oy + 1) * SRC_H // OUT_H)
        row = bytearray(OUT_W)
        for ox in range(OUT_W):
            x0 = ox * SRC_W // OUT_W
            x1 = max(x0 + 1, (ox + 1) * SRC_W // OUT_W)
            total = 0
            count = 0
            for y in range(y0, y1):
                base = y * SRC_W
                for x in range(x0, x1):
                    total += src[base + x]
                    count += 1
            row[ox] = 1 if total < thr * count else 0
        rows.append(row)
    return rows


def to_xbm(rows) -> bytes:
    out = bytearray()
    for row in rows:
        for b in range((OUT_W + 7) // 8):
            byte = 0
            for i in range(8):
                x = b * 8 + i
                if x < OUT_W and row[x]:
                    byte |= 1 << i
            out.append(byte)
    return bytes(out)


HEADER = """\
// ---------------------------------------------------------------------------
// AUTO-GENERATED FILE - do not edit by hand.
//
// {w} x {h} pixel 1-bit XBM frames for U8g2::drawXBM(), rendered from the
// original BongoCat artwork (https://github.com/ayangweb/BongoCat, MIT).
// Regenerate with:  python tools/make_art.py
// ---------------------------------------------------------------------------
#pragma once

#include <stdint.h>

#define BONGO_FRAME_W {w}
#define BONGO_FRAME_H {h}
#define BONGO_FRAME_BYTES ({w} * {h} / 8)
"""


def emit(frame_bits, path: str) -> None:
    parts = [HEADER.format(w=OUT_W, h=OUT_H)]
    for name, bits in frame_bits.items():
        data = to_xbm(bits)
        assert len(data) == OUT_W * OUT_H // 8, len(data)
        parts.append("\n// %s\nstatic const uint8_t bongo_frame_%s"
                     "[BONGO_FRAME_BYTES] = {" % (name, name))
        for i in range(0, len(data), 20):
            parts.append("\n  " + ",".join("0x%02X" % b for b in data[i:i + 20])
                         + ",")
        parts.append("\n};\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(parts))


def contact_sheet(frame_bits, path: str, cols: int = 2, scale: int = 2) -> None:
    """Render the final 1-bit frames into one PNG so the art can be eyeballed."""
    names = list(frame_bits)
    rows_n = (len(names) + cols - 1) // cols
    pad = 6
    cw, ch = OUT_W * scale + pad, OUT_H * scale + pad
    W, H = cols * cw + pad, rows_n * ch + pad
    sheet = [[170] * W for _ in range(H)]
    for idx, name in enumerate(names):
        bits = frame_bits[name]
        ox = pad + (idx % cols) * cw
        oy = pad + (idx // cols) * ch
        for y in range(OUT_H):
            row = bits[y]
            for x in range(OUT_W):
                v = 0 if row[x] else 255
                for sy in range(scale):
                    dst = sheet[oy + y * scale + sy]
                    for sx in range(scale):
                        dst[ox + x * scale + sx] = v
    flat = bytearray()
    for row in sheet:
        flat.extend(bytes(row))
    write_gray(path, W, H, flat)


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desk", default=os.path.join(ASSETS, "desk.png"))
    ap.add_argument("--cat", default=os.path.join(ASSETS, "cat.png"))
    ap.add_argument("--out", default=os.path.join(
        ROOT, "firmware", "bongocat_rlcd", "art_bongocat.h"))
    ap.add_argument("--preview", nargs="?",
                    const=os.path.join(ROOT, "docs", "art_preview.png"))
    ap.add_argument("--threshold", type=int, default=150,
                    help="1-bit threshold on the down-sampled luminance")
    ap.add_argument("--cat-scale", type=float, default=CAT_SCALE,
                    help="cat size relative to the original render "
                         "(default %.2f; 1.0 = upstream proportions)"
                         % CAT_SCALE)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("\n".join(FRAMES))
        return 0

    for p in (args.desk, args.cat):
        if not os.path.isfile(p):
            print("!! missing %s\n   run tools/extract_source_art.py first" % p)
            return 1

    dw, dh, desk = read_rgba(args.desk)
    cw, chh, cat = read_rgba(args.cat)
    if (dw, dh) != (SRC_W, SRC_H) or (cw, chh) != (SRC_W, SRC_H):
        print("!! expected %dx%d assets, got desk %dx%d cat %dx%d"
              % (SRC_W, SRC_H, dw, dh, cw, chh))
        return 1

    scene = Scene(desk, cat)
    poses = scene.poses()
    raw = {name: scene.render(cat_scale=args.cat_scale, **poses[name])
           for name in FRAMES}
    bits = {name: downscale(raw[name], args.threshold) for name in FRAMES}

    emit(bits, args.out)
    print("wrote %s (%d frames, %dx%d, %d bytes each, cat scale %.2f)"
          % (os.path.relpath(args.out, ROOT), len(bits), OUT_W, OUT_H,
             OUT_W * OUT_H // 8, args.cat_scale))

    if args.preview:
        os.makedirs(os.path.dirname(os.path.abspath(args.preview)), exist_ok=True)
        contact_sheet(bits, args.preview)
        print("wrote %s" % os.path.relpath(args.preview, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
