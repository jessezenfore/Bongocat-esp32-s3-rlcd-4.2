#!/usr/bin/env python3
"""Package the GUI into a single Windows executable.

    python host/build_exe.py            # -> dist/BongoCat.exe
    python host/build_exe.py --console  # keep a console for debugging

The result is self-contained: Python, tkinter, pyserial, psutil, Pillow,
pystray and the WinRT notification bindings are all bundled, so the exe runs on
a machine with nothing installed.

Notification support needs winsdk; when it is missing the build still succeeds
and the GUI simply reports that notification forwarding is unavailable.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

APP_NAME = "BongoCat"

# Imported lazily inside functions, so PyInstaller's static analysis cannot see
# them; they have to be named explicitly.
HIDDEN = [
    "pystray._win32",
    "PIL._tkinter_finder",
    "serial.tools.list_ports",
    "engine", "config", "banner", "notify", "keymon",
]

# winsdk is a large namespace package; pull in just the projections we touch.
WINRT_MODULES = [
    "winsdk.windows.ui.notifications",
    "winsdk.windows.ui.notifications.management",
    "winsdk.windows.data.xml.dom",
]


def have(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--console", action="store_true",
                    help="build with a console window (useful for debugging)")
    ap.add_argument("--onedir", action="store_true",
                    help="emit a folder instead of a single file (starts faster)")
    args = ap.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed:  pip install pyinstaller",
              file=sys.stderr)
        return 2

    for out in ("build", "dist", "%s.spec" % APP_NAME):
        p = os.path.join(HERE, out)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        elif os.path.isfile(p):
            os.remove(p)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        os.path.join(HERE, "gui.py"),
        "--name", APP_NAME,
        "--noconfirm", "--clean",
        "--onedir" if args.onedir else "--onefile",
        "--console" if args.console else "--windowed",
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "build"),
        "--specpath", HERE,
    ]
    for mod in HIDDEN:
        cmd += ["--hidden-import", mod]

    if have("winsdk"):
        for mod in WINRT_MODULES:
            cmd += ["--hidden-import", mod]
    else:
        print("note: winsdk not installed - building without notification "
              "forwarding support")

    # Keep the exe honest about the project it came from.
    cmd += ["--add-data", "%s%s%s" % (os.path.join(ROOT, "docs", "PROTOCOL.md"),
                                      os.pathsep, ".")]

    print("running:", " ".join(cmd[:6]), "...")
    rc = subprocess.call(cmd, cwd=HERE)
    if rc != 0:
        print("PyInstaller failed with %d" % rc, file=sys.stderr)
        return rc

    target = os.path.join(HERE, "dist", APP_NAME + ("" if args.onedir else ".exe"))
    if os.path.isdir(target):
        exe = os.path.join(target, APP_NAME + ".exe")
        total = sum(os.path.getsize(os.path.join(dp, f))
                    for dp, _, fs in os.walk(target) for f in fs)
        print("\nbuilt %s  (%.1f MB total)" % (target, total / 1e6))
    elif os.path.isfile(target):
        print("\nbuilt %s  (%.1f MB)" % (target, os.path.getsize(target) / 1e6))
    else:
        print("\nwarning: expected output not found at %s" % target)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
