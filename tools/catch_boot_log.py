#!/usr/bin/env python3
"""Catch the boot log of an ESP32-S3 that keeps resetting.

When a board is stuck in a reset loop its USB-CDC port disconnects and
re-enumerates several times a second, so a normal serial monitor usually shows
nothing useful.  This tool keeps re-opening the port and dumps whatever arrives,
timestamped, so the ROM banner, the reset reason and any panic backtrace can be
read off.

Usage::

    python tools/catch_boot_log.py                 # auto-detect the port
    python tools/catch_boot_log.py --port COM7
    python tools/catch_boot_log.py --seconds 30    # stop after 30 s
"""

from __future__ import annotations

import argparse
import os
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial is not installed:  pip install pyserial", file=sys.stderr)
    raise SystemExit(2)

BAUD = 115200


def autodetect() -> str | None:
    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    for p in ports:
        blob = "%s %s %s" % (p.device, p.description or "", p.manufacturer or "")
        if any(k in blob.lower() for k in ("jtag", "esp32", "espressif", "cdc",
                                           "usb serial")):
            return p.device
    return ports[0].device if ports else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default=None,
                    help="serial port (default: auto-detect)")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="stop after this many seconds (0 = run until ctrl-c)")
    ap.add_argument("--list", action="store_true", help="list ports and exit")
    args = ap.parse_args()

    if args.list:
        for p in sorted(list_ports.comports(), key=lambda p: p.device):
            print("%-8s %s" % (p.device, p.description or "?"))
        return 0

    port = args.port or autodetect()
    if not port:
        print("no serial port found", file=sys.stderr)
        return 1

    t0 = time.monotonic()
    deadline = (t0 + args.seconds) if args.seconds > 0 else None

    print("watching %s @ %d -- ctrl-c to stop" % (port, BAUD))
    print("(a board stuck in a reset loop makes the port blink; this keeps up "
          "with it)\n")

    opens = 0
    total_bytes = 0
    ser = None
    buf = bytearray()

    try:
        while True:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                break

            if ser is None:
                try:
                    ser = serial.Serial(port, BAUD, timeout=0)
                    opens += 1
                    print("\n--- [%6.2fs] port open #%d ---"
                          % (now - t0, opens), flush=True)
                except Exception:
                    time.sleep(0.05)
                    continue

            try:
                chunk = ser.read(8192)
            except Exception:
                chunk = b""
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
                print("\n--- [%6.2fs] port lost (board reset?) ---"
                      % (time.monotonic() - t0), flush=True)
                continue

            if chunk:
                total_bytes += len(chunk)
                buf.extend(chunk)
                while b"\n" in buf:
                    line, _, rest = buf.partition(b"\n")
                    buf = bytearray(rest)
                    text = line.decode("utf-8", "replace").rstrip("\r")
                    print("[%7.3fs] %s" % (time.monotonic() - t0, text),
                          flush=True)
            else:
                time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    print("\ncaptured %d bytes over %d port open(s) in %.1fs"
          % (total_bytes, opens, time.monotonic() - t0))
    if total_bytes == 0:
        print("nothing received. If the port is blinking, try again while "
              "holding BOOT to keep the chip in download mode, or check that "
              "no serial monitor is holding the port.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
