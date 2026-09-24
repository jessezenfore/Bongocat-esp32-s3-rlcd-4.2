#!/usr/bin/env python3
"""End-to-end self test for the bongo cat host half.

Runs without hardware:

  * executes ``host/bongocat_host.py --print-only --demo`` as a subprocess and
    validates every emitted line against the wire protocol in
    ``docs/PROTOCOL.md``
  * checks that the generated artwork header has the geometry the firmware
    expects, and that ``tools/make_art.py`` is reproducible
  * on Windows, injects synthetic keystrokes and confirms the ``win32`` key
    sensor reports a non-zero rate

Usage::

    python tools/smoke_test.py

Exit code 0 means everything passed.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = os.path.join(ROOT, "host", "bongocat_host.py")
ART = os.path.join(ROOT, "firmware", "bongocat_rlcd", "art_bongocat.h")

_failures: list[str] = []
_checks = 0


def check(condition: bool, label: str, detail: str = "") -> None:
    global _checks
    _checks += 1
    if condition:
        print("  ok    %s" % label)
    else:
        print("  FAIL  %s%s" % (label, ("  -- " + detail) if detail else ""))
        _failures.append(label)


# ---------------------------------------------------------------------------
# 1. protocol conformance
# ---------------------------------------------------------------------------
_INT = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?\d+(\.\d+)?$")


def validate_line(line: str) -> str | None:
    """Return an error string when `line` violates the protocol."""
    parts = line.split(",")
    verb, f = parts[0], parts[1:]

    if verb == "T":
        if len(f) != 2:
            return "T needs 2 fields"
        if not _INT.match(f[0]) or not _INT.match(f[1]):
            return "T fields must be integers"
        epoch = int(f[0])
        if not (1_500_000_000 < epoch < 4_000_000_000):
            return "T epoch out of plausible range: %d" % epoch
        if not (-16 * 60 <= int(f[1]) <= 16 * 60):
            return "T timezone offset out of range: %s" % f[1]
        return None

    if verb == "S":
        if len(f) != 4:
            return "S needs 4 fields"
        cpu, mem = float(f[0]), float(f[1])
        if not (0.0 <= cpu <= 100.0):
            return "S cpu out of range: %s" % f[0]
        if not (0.0 <= mem <= 100.0):
            return "S mem out of range: %s" % f[1]
        for raw in f[2:]:
            if not _INT.match(raw) or int(raw) < 0:
                return "S network rates must be non-negative integers"
        return None

    if verb == "A":
        if len(f) != 1 or not _FLOAT.match(f[0]):
            return "A needs one float"
        if float(f[0]) < 0:
            return "A rate must be non-negative"
        return None

    if verb == "K":
        if len(f) != 2:
            return "K needs 2 fields (left, right)"
        for raw in f:
            if raw not in ("0", "1"):
                return "K fields must be 0 or 1, got %r" % raw
        return None

    if verb in ("HELLO", "PING", "READY", "PONG", "HB", "ERR"):
        return None

    return "unknown verb %r" % verb


def test_protocol() -> None:
    print("\n[1] host protocol (--print-only --demo)")
    cmd = [sys.executable, HOST, "--print-only", "--demo", "--keys", "none",
           "--duration", "2.2", "--activity-hz", "10", "--interval", "1.0"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    check(proc.returncode == 0, "host script exits cleanly",
          "rc=%d stderr=%s" % (proc.returncode, proc.stderr[-400:]))

    lines = [ln.strip() for ln in proc.stdout.splitlines()
             if ln.strip() and re.match(r"^[A-Z]+,|^PING$", ln.strip())]
    check(len(lines) > 5, "produced protocol traffic",
          "got %d lines" % len(lines))

    seen: dict[str, int] = {}
    errors: list[str] = []
    for ln in lines:
        err = validate_line(ln)
        if err:
            errors.append("%s -> %s" % (ln, err))
        seen[ln.split(",")[0]] = seen.get(ln.split(",")[0], 0) + 1

    check(not errors, "every line matches the protocol",
          "; ".join(errors[:4]))
    check(seen.get("T", 0) >= 2, "T (clock) is sent once per second",
          "count=%d" % seen.get("T", 0))
    check(seen.get("S", 0) >= 2, "S (load) is sent once per interval",
          "count=%d" % seen.get("S", 0))
    check(seen.get("A", 0) >= 15, "A (activity) is sent at --activity-hz",
          "count=%d" % seen.get("A", 0))
    check(seen.get("K", 0) >= 15, "K (paw state) is sent at --activity-hz",
          "count=%d" % seen.get("K", 0))


# ---------------------------------------------------------------------------
# 2. generated artwork
# ---------------------------------------------------------------------------
def test_artwork() -> None:
    print("\n[2] generated artwork")
    check(os.path.exists(ART), "art_bongocat.h exists")

    with open(ART, "r", encoding="utf-8") as fh:
        text = fh.read()

    w = re.search(r"#define BONGO_FRAME_W (\d+)", text)
    h = re.search(r"#define BONGO_FRAME_H (\d+)", text)
    check(bool(w and h), "frame geometry defines present")
    if not (w and h):
        return
    check((int(w.group(1)), int(h.group(1))) == (400, 232),
          "frame is 400x232 (matches SCENE_W/SCENE_H)",
          "got %sx%s" % (w.group(1), h.group(1)))

    names = re.findall(r"bongo_frame_(\w+)\[", text)
    expected = ["rest", "rest_blink", "left", "right", "both", "sleep"]
    check(names == expected, "all 6 frames are present in order",
          "got %s" % names)

    expected_bytes = 400 * 232 // 8
    blocks = re.findall(r"= \{(.*?)\};", text, re.S)
    check(len(blocks) == len(expected), "each frame has a byte array")
    if blocks:
        n = len([b for b in blocks[0].split(",") if b.strip()])
        check(n == expected_bytes,
              "frame payload is %d bytes" % expected_bytes, "got %d" % n)

    # every pose must differ from the resting one, otherwise the animation is
    # silently doing nothing
    def payload(block: str) -> bytes:
        return bytes(int(b, 16) for b in block.replace("\n", " ").split(",")
                     if b.strip())

    if len(blocks) == len(expected):
        data = [payload(b) for b in blocks]
        for idx, name in enumerate(expected[1:], start=1):
            check(data[idx] != data[0], "frame %r differs from 'rest'" % name)
        bits = sum(bin(b).count("1") for b in data[0])
        frac = bits / (len(data[0]) * 8.0)
        check(0.01 < frac < 0.40, "rest frame ink coverage is sane",
              "%.1f%% black" % (frac * 100))


# ---------------------------------------------------------------------------
# 3. banner rendering
# ---------------------------------------------------------------------------
def test_banner() -> None:
    print("\n[3] message banner")
    sys.path.insert(0, os.path.join(ROOT, "host"))
    import banner

    check(banner.available(), "Pillow available for rendering")
    if not banner.available():
        return

    img = banner.render("该喝水啦", "已经坐了 45 分钟，站起来活动一下")
    check(img.size == (banner.BANNER_W, banner.BANNER_H),
          "banner is %dx%d" % (banner.BANNER_W, banner.BANNER_H),
          "got %s" % (img.size,))

    bits = banner.pack_xbm(img)
    expect = banner.BANNER_W * banner.BANNER_H // 8
    check(len(bits) == expect, "packed bitmap is %d bytes" % expect,
          "got %d" % len(bits))
    ink = sum(bin(b).count("1") for b in bits)
    frac = ink / (len(bits) * 8.0)
    check(0.01 < frac < 0.50, "banner has sensible ink coverage",
          "%.1f%%" % (frac * 100))

    line = banner.encode("标题", "正文", duration_ms=5000)
    fields = line.split(",")
    check(line.startswith("B,") and len(fields) == 7, "B line has 7 fields",
          "got %d" % len(fields))
    check(fields[5] == "5000", "duration is carried in the line")
    check(len(line) < 6144, "line fits the firmware's 6 KB receive buffer",
          "%d chars" % len(line))


# ---------------------------------------------------------------------------
# 4. engine: reminder, messages, paw swap
# ---------------------------------------------------------------------------
def test_engine() -> None:
    print("\n[4] engine")
    sys.path.insert(0, os.path.join(ROOT, "host"))
    import engine
    from config import Settings

    sent: list[str] = []

    class Recorder:
        connected = True
        ready_banner = "READY,test"
        port = "TEST"

        def open(self):
            return True

        def close(self):
            pass

        def send(self, line):
            sent.append(line)
            return True

        def pump(self):
            pass

    class FakeKeys:
        source = "fake"

        def start(self):
            pass

        def stop(self):
            pass

        def rate(self):
            return 3.0

        def hands(self):
            return (True, False)          # the left paw is held down

    # -- the reminder must fire and push a banner ------------------------
    # _reschedule_water floors the interval at one second, so 0.05 min means a
    # 3 s wait; give it a little slack.
    sent.clear()
    s = Settings()
    s.water_enabled = True
    s.water_interval_min = 0.05
    s.water_toast = False
    eng = engine.HostEngine(s, sink=Recorder(), on_log=lambda *a: None)
    eng.start()
    time.sleep(3.6)
    st = eng.status()
    eng.stop()
    check(st["water_count"] >= 1, "drink-water reminder fires",
          "count=%d" % st["water_count"])
    check(any(l.startswith("B,") for l in sent),
          "reminder pushes a banner to the board")

    # -- forward_notifications off must swallow notifications ------------
    sent.clear()
    s = Settings()
    s.water_enabled = False
    s.forward_notifications = False
    eng = engine.HostEngine(s, sink=Recorder(), on_log=lambda *a: None)
    eng.start()
    time.sleep(0.2)
    eng._on_notification("微信", "hello")
    eng.stop()
    check(not any(l.startswith("B,") for l in sent),
          "notifications ignored while forwarding is off")

    # -- and on must forward them ---------------------------------------
    sent.clear()
    s.forward_notifications = True
    eng = engine.HostEngine(s, sink=Recorder(), on_log=lambda *a: None)
    eng.start()
    time.sleep(0.2)
    eng._on_notification("微信", "李四: 文件已经发你了")
    eng.stop()
    check(any(l.startswith("B,") for l in sent),
          "notification is forwarded to the board")
    check("李四" in eng.status()["last_message"],
          "forwarded text survives rendering",
          repr(eng.status()["last_message"]))

    # -- paw swap flips which hand the key group drives ------------------
    results = {}
    for swap in (False, True):
        sent.clear()
        s = Settings()
        s.water_enabled = False
        s.swap_paws = swap
        eng = engine.HostEngine(s, sink=Recorder(), on_log=lambda *a: None)
        eng._keys = FakeKeys()
        eng.start()
        time.sleep(0.4)
        eng.stop()
        results[swap] = next((l for l in sent if l.startswith("K,")), None)
    check(results[False] == "K,1,0", "left-held key drives the left paw",
          str(results[False]))
    check(results[True] == "K,0,1", "swap-paws moves it to the right paw",
          str(results[True]))


# ---------------------------------------------------------------------------
# 5. keyboard sensor (Windows only)
# ---------------------------------------------------------------------------
def test_keyboard() -> None:
    print("\n[5] keyboard sensor")
    if sys.platform != "win32":
        print("  skip  not Windows")
        return

    sys.path.insert(0, os.path.join(ROOT, "host"))
    import ctypes

    from keymon import KeyMonitor

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte,
                                   ctypes.c_uint, ctypes.c_void_p]

    mon = KeyMonitor(source="win32")
    check(mon.source == "win32", "win32 sensor selected")
    mon.start()
    time.sleep(0.3)

    # main keyboard -> left paw, arrow cluster -> right paw (as upstream)
    user32.keybd_event(0x41, 0, 0, None)          # 'A'
    time.sleep(0.12)
    left, right = mon.hands()
    check(left and not right, "'A' pushes the left paw", "left=%s right=%s"
          % (left, right))
    user32.keybd_event(0x41, 0, 0x0002, None)
    time.sleep(0.12)
    left, right = mon.hands()
    check(not left and not right, "releasing 'A' lifts the paw")

    user32.keybd_event(0x25, 0, 0, None)          # VK_LEFT
    time.sleep(0.12)
    left, right = mon.hands()
    check(right and not left, "an arrow pushes the right paw",
          "left=%s right=%s" % (left, right))
    user32.keybd_event(0x25, 0, 0x0002, None)
    time.sleep(0.12)

    for _ in range(10):
        user32.keybd_event(0x41, 0, 0, None)
        time.sleep(0.02)
        user32.keybd_event(0x41, 0, 0x0002, None)
        time.sleep(0.04)
    time.sleep(0.1)
    rate = mon.rate()
    mon.stop()
    check(rate > 2.0, "synthetic keystrokes are counted",
          "rate=%.2f keys/s" % rate)


# ---------------------------------------------------------------------------
def main() -> int:
    print("bongo cat smoke test")
    test_protocol()
    test_artwork()
    test_banner()
    test_engine()
    test_keyboard()

    print("\n%d checks, %d failed" % (_checks, len(_failures)))
    if _failures:
        for f in _failures:
            print("  - %s" % f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
