#!/usr/bin/env python3
"""Minimal pure-stdlib PNG reader/writer.

Only what the bongo cat asset pipeline needs: read any non-interlaced 8-bit PNG
and normalise it to RGBA, and write RGBA or 8-bit greyscale PNGs.  Keeping this
dependency-free means ``tools/make_art.py`` runs on a bare Python install.
"""

from __future__ import annotations

import struct
import zlib

__all__ = ["read_rgba", "write_rgba", "write_gray", "over_white"]

_SIG = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _unfilter(raw: bytes, w: int, h: int, channels: int) -> bytearray:
    stride = w * channels
    out = bytearray(h * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                line[i] = (line[i] + pr) & 0xFF
        else:
            raise ValueError("bad PNG filter type %d" % ftype)
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def read_rgba(path: str):
    """Return (width, height, bytearray of RGBA bytes)."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != _SIG:
        raise ValueError("%s is not a PNG" % path)

    pos = 8
    idat = bytearray()
    palette = None
    trns = None
    width = height = depth = ctype = None

    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(
                ">IIBBBBB", chunk)
            if interlace:
                raise ValueError("interlaced PNG not supported")
        elif tag == b"IDAT":
            idat += chunk
        elif tag == b"PLTE":
            palette = chunk
        elif tag == b"tRNS":
            trns = chunk
        elif tag == b"IEND":
            break

    if depth != 8:
        raise ValueError("only 8-bit PNGs supported (got %s)" % depth)
    channels = _CHANNELS[ctype]
    raw = zlib.decompress(bytes(idat))
    px = _unfilter(raw, width, height, channels)

    n = width * height
    rgba = bytearray(n * 4)

    if ctype == 6:
        rgba[:] = px
    elif ctype == 2:
        for i in range(n):
            rgba[i * 4:i * 4 + 3] = px[i * 3:i * 3 + 3]
            rgba[i * 4 + 3] = 255
    elif ctype == 0:
        for i in range(n):
            v = px[i]
            rgba[i * 4] = rgba[i * 4 + 1] = rgba[i * 4 + 2] = v
            rgba[i * 4 + 3] = 255
    elif ctype == 4:
        for i in range(n):
            v = px[i * 2]
            rgba[i * 4] = rgba[i * 4 + 1] = rgba[i * 4 + 2] = v
            rgba[i * 4 + 3] = px[i * 2 + 1]
    elif ctype == 3:
        for i in range(n):
            idx = px[i]
            rgba[i * 4:i * 4 + 3] = palette[idx * 3:idx * 3 + 3]
            rgba[i * 4 + 3] = trns[idx] if trns and idx < len(trns) else 255
    else:
        raise ValueError("unsupported colour type %s" % ctype)

    return width, height, rgba


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def _encode(raw: bytearray, width: int, height: int, ctype: int) -> bytes:
    channels = _CHANNELS[ctype]
    stride = width * channels
    filtered = bytearray()
    for y in range(height):
        filtered.append(0)                       # filter type "None"
        filtered += raw[y * stride:(y + 1) * stride]
    return (_SIG
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, ctype,
                                          0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(filtered), 9))
            + _chunk(b"IEND", b""))


def write_rgba(path: str, width: int, height: int, rgba) -> None:
    with open(path, "wb") as fh:
        fh.write(_encode(bytearray(rgba), width, height, 6))


def write_gray(path: str, width: int, height: int, gray) -> None:
    with open(path, "wb") as fh:
        fh.write(_encode(bytearray(gray), width, height, 0))


def over_white(rgba, count: int) -> bytearray:
    """Flatten an RGBA buffer onto white, returning packed RGB bytes.

    The upstream BongoCat layers store fully transparent pixels as (0,0,0,0).
    Reading their RGB directly would treat every transparent pixel as opaque
    black, so everything that samples those layers has to go through this
    first -- otherwise whole transparent regions render as black bands.
    """
    out = bytearray(count * 3)
    for i in range(count):
        o = i * 4
        a = rgba[o + 3]
        if a == 255:
            out[i * 3] = rgba[o]
            out[i * 3 + 1] = rgba[o + 1]
            out[i * 3 + 2] = rgba[o + 2]
            continue
        inv = 255 - a
        out[i * 3] = (rgba[o] * a + 255 * inv) // 255
        out[i * 3 + 1] = (rgba[o + 1] * a + 255 * inv) // 255
        out[i * 3 + 2] = (rgba[o + 2] * a + 255 * inv) // 255
    return out
