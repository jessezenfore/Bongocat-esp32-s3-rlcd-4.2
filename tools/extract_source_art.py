#!/usr/bin/env python3
"""Extract reusable 1-bit source art from the original BongoCat project.

The upstream app (https://github.com/ayangweb/BongoCat, MIT) composites three
layers:

    1. ``resources/background.png``  desk + arrow keys + keyboard (no cat)
    2. a Live2D model                the cat itself
    3. ``resources/{left,right}-keys/*.png``
                                     a full-canvas overlay per pressed key

The cat only exists as a Live2D model, so we recover its pixels by subtracting
the background from the shipped ``resources/cover.png`` render.  That gives us
the exact upstream artwork, which we then hand to ``tools/make_art.py``.

Usage::

    python tools/extract_source_art.py --repo BongoCat --model keyboard
    python tools/extract_source_art.py --repo BongoCat --model keyboard --preview

Outputs live in ``tools/assets/``: ``desk.png`` and ``cat.png`` (both RGBA).
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pngmini import read_rgba, write_gray, write_rgba  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

# A pixel belongs to the cat when the render differs from the bare background.
DIFF_THRESHOLD = 26


def over_white(w: int, h: int, rgba) -> bytearray:
    """Flatten an RGBA buffer onto white, returning packed RGB bytes.

    Both upstream images are RGBA and store transparent pixels as (0,0,0,0);
    without this step those would read as opaque black and swamp the diff.
    """
    n = w * h
    out = bytearray(n * 3)
    for i in range(n):
        o = i * 4
        a = rgba[o + 3]
        if a == 255:
            out[i * 3] = rgba[o]
            out[i * 3 + 1] = rgba[o + 1]
            out[i * 3 + 2] = rgba[o + 2]
        else:
            inv = 255 - a
            out[i * 3] = (rgba[o] * a + 255 * inv) // 255
            out[i * 3 + 1] = (rgba[o + 1] * a + 255 * inv) // 255
            out[i * 3 + 2] = (rgba[o + 2] * a + 255 * inv) // 255
    return out


def extract(repo: str, model: str, preview: bool) -> int:
    res = os.path.join(repo, "src-tauri", "assets", "models", model, "resources")
    cover_path = os.path.join(res, "cover.png")
    bg_path = os.path.join(res, "background.png")
    for p in (cover_path, bg_path):
        if not os.path.isfile(p):
            print("!! missing %s" % p)
            return 1

    cw, ch, cover_rgba = read_rgba(cover_path)
    bw, bh, back_rgba = read_rgba(bg_path)
    if (cw, ch) != (bw, bh):
        print("!! cover %dx%d and background %dx%d differ in size"
              % (cw, ch, bw, bh))
        return 1
    print("source: %s  %dx%d" % (model, cw, ch))

    cover = over_white(cw, ch, cover_rgba)
    back = over_white(bw, bh, back_rgba)

    n = cw * ch
    cat = bytearray(n * 4)
    is_cat = bytearray(n)

    min_x, min_y, max_x, max_y = cw, ch, -1, -1
    for i in range(n):
        o = i * 3
        d = (abs(cover[o] - back[o])
             + abs(cover[o + 1] - back[o + 1])
             + abs(cover[o + 2] - back[o + 2]))
        if d > DIFF_THRESHOLD:
            q = i * 4
            cat[q] = cover[o]
            cat[q + 1] = cover[o + 1]
            cat[q + 2] = cover[o + 2]
            cat[q + 3] = 255
            is_cat[i] = 1
            x, y = i % cw, i // cw
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y

    if max_x < 0:
        print("!! nothing extracted - cover and background look identical")
        return 1
    print("cat bbox: x %d..%d  y %d..%d  (%d opaque px)"
          % (min_x, max_x, min_y, max_y, sum(is_cat)))

    # ---- where are the pink paw pads? ------------------------------------
    # Upstream paints the pads pink; locating them tells us where each paw is,
    # which is what the two "hand down" parameters animate.
    pads = []
    for i in range(n):
        if not is_cat[i]:
            continue
        o = i * 4
        r, g, b = cat[o], cat[o + 1], cat[o + 2]
        if r > 190 and g < 170 and b < 190 and r - g > 55:
            pads.append((i % cw, i // cw))
    if pads:
        xs = sorted(p[0] for p in pads)
        mid = (xs[0] + xs[-1]) // 2
        left = [p for p in pads if p[0] <= mid]
        right = [p for p in pads if p[0] > mid]
        for name, pts in (("left", left), ("right", right)):
            if not pts:
                continue
            px = [p[0] for p in pts]
            py = [p[1] for p in pts]
            print("pink %-5s paw: x %d..%d  y %d..%d  (%d px)"
                  % (name, min(px), max(px), min(py), max(py), len(pts)))
    else:
        print("pink paw pads: none found")

    # ---- desk edge profile ------------------------------------------------
    # The thick black diagonal in the background occludes the cat's arms, so
    # record its y position per column.
    profile = []
    for x in range(cw):
        top = -1
        for y in range(ch):
            o = (y * cw + x) * 3
            if back[o] < 90 and back[o + 1] < 90 and back[o + 2] < 90:
                top = y
                break
        profile.append(top)
    found = [p for p in profile if p >= 0]
    if found:
        print("desk edge: y %d (left) .. %d (right), %d/%d columns"
              % (found[0], found[-1], len(found), cw))

    os.makedirs(ASSETS, exist_ok=True)
    desk_path = os.path.join(ASSETS, "desk.png")
    cat_path = os.path.join(ASSETS, "cat.png")
    write_rgba(desk_path, cw, ch, back_rgba)
    write_rgba(cat_path, cw, ch, cat)
    print("wrote %s" % os.path.relpath(desk_path, HERE))
    print("wrote %s" % os.path.relpath(cat_path, HERE))

    if preview:
        # cat over white, next to the desk, so both can be eyeballed
        pad = 8
        W = cw * 2 + pad * 3
        H = ch + pad * 2
        sheet = bytearray(b"\xff" * (W * H))
        for x in range(cw):
            for y in range(ch):
                i = y * cw + x
                q = i * 4
                if cat[q + 3]:
                    v = (cat[q] * 299 + cat[q + 1] * 587
                         + cat[q + 2] * 114) // 1000
                else:
                    v = 255
                sheet[(y + pad) * W + (x + pad)] = v
                o = i * 3
                v2 = (back[o] * 299 + back[o + 1] * 587
                      + back[o + 2] * 114) // 1000
                sheet[(y + pad) * W + (x + pad * 2 + cw)] = v2
        out = os.path.join(ASSETS, "extract_preview.png")
        write_gray(out, W, H, sheet)
        print("wrote %s" % os.path.relpath(out, HERE))

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="BongoCat",
                    help="path to the cloned ayangweb/BongoCat repository")
    ap.add_argument("--model", default="keyboard",
                    choices=["keyboard", "standard", "gamepad"],
                    help="which bundled model to take art from")
    ap.add_argument("--preview", action="store_true",
                    help="also write tools/assets/extract_preview.png")
    args = ap.parse_args()
    return extract(args.repo, args.model, args.preview)


if __name__ == "__main__":
    sys.exit(main())
