#!/usr/bin/env python3
"""Stream this PC's clock, load and typing rate to the bongo cat board.

This is the headless half of the project.  For the windowed application with
the drink-water reminder, the message box and the system tray, run
``python host/gui.py`` (or the packaged exe) instead -- both drive the same
engine and share ``config.json``.

Wire protocol: see ../docs/PROTOCOL.md

Examples
--------
    python bongocat_host.py --list-ports
    python bongocat_host.py                      # auto-detect the port
    python bongocat_host.py --port COM7
    python bongocat_host.py --demo               # fake data, no board needed
    python bongocat_host.py --print-only         # show the protocol, send nothing
    python bongocat_host.py --message 该喝水啦
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import default_settings  # noqa: E402
from engine import (HostEngine, PrintSink, SerialSink, autodetect_port,  # noqa: E402
                    describe_ports, human_rate)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Stream PC time/CPU/RAM/network/typing stats to the "
                    "ESP32-S3-RLCD-4.2 bongo cat.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples")[-1])
    ap.add_argument("--port", default=None,
                    help="serial port (COM7, /dev/ttyACM0). "
                         "Default: auto-detect. Use 'none' for --print-only.")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--interval", type=float, default=1.0,
                    help="seconds between CPU/RAM/network samples (default 1.0)")
    ap.add_argument("--activity-hz", type=float, default=20.0,
                    help="paw-state updates per second (default 20)")
    ap.add_argument("--keys", default="auto",
                    choices=["auto", "win32", "pynput", "none"])
    ap.add_argument("--swap-paws", action="store_true",
                    help="swap the cat's hands: main keyboard -> right paw")
    ap.add_argument("--demo", action="store_true",
                    help="synthesise CPU/RAM/network instead of reading psutil")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="stop after this many seconds (0 = run until ctrl-c)")
    ap.add_argument("--message", default=None,
                    help="send one message banner to the board and exit")
    ap.add_argument("--message-seconds", type=float, default=8.0)
    ap.add_argument("--print-only", action="store_true",
                    help="print the protocol lines instead of sending them")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_ports:
        ports = describe_ports()
        print("\n".join("%-8s %s" % (d, p) for d, p in ports)
              if ports else "no serial ports found")
        return 0

    settings = default_settings()
    settings.baud = args.baud
    settings.stats_interval = args.interval
    settings.activity_hz = args.activity_hz
    settings.key_source = args.keys
    settings.swap_paws = args.swap_paws or settings.swap_paws
    settings.message_seconds = args.message_seconds

    if args.print_only:
        args.port = None
    elif args.port is None:
        args.port = autodetect_port()
        if args.port is None:
            print("No serial port detected. Connect the board, or pass --port. "
                  "Falling back to --print-only.\n", file=sys.stderr)
            args.print_only = True
    elif args.port.lower() == "none":
        args.port = None
        args.print_only = True
    settings.port = args.port or ""

    def log(message: str, always: bool = False) -> None:
        if args.verbose or always:
            print("[%s] %s" % (time.strftime("%H:%M:%S"), message), flush=True)

    sink = PrintSink(log) if args.print_only else SerialSink(settings.port,
                                                             settings.baud, log)
    engine = HostEngine(settings, sink=sink, demo=args.demo, on_log=log)

    print("bongocat host  |  protocol v1")
    print("  port      : %s" % (args.port or "none (--print-only)"))
    print("  paw swap  : %s" % ("on" if settings.swap_paws else "off"))
    print("  stats     : every %.2fs   paws: %.0f Hz"
          % (settings.stats_interval, settings.activity_hz))
    print("  ctrl-c to stop\n")

    engine.start()

    if args.message is not None:
        time.sleep(1.0 if not args.print_only else 0.1)
        engine.send_message(args.message, "", args.message_seconds)
        time.sleep(1.0)
        engine.stop()
        return 0

    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    last_summary = 0.0
    try:
        while True:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                break
            if now - last_summary >= 1.0:
                last_summary = now
                st = engine.status()
                print("  CPU %5.1f%%  RAM %5.1f%%  NET v %-9s ^ %-9s"
                      "  keys %4.1f/s  paw %s%s  [%s]   "
                      % (st["cpu"], st["mem"], human_rate(st["down"]),
                         human_rate(st["up"]), st["keys_per_sec"],
                         "L" if st["left"] else "-", "R" if st["right"] else "-",
                         "READY" if st["ready"] else
                         ("linked" if st["connected"] else "no link")),
                      end="\r" if not args.print_only else "\n", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        engine.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
