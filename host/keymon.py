"""Keyboard-activity sensors for the bongo cat host.

The cat copies the original BongoCat app: keys on the main keyboard push the
**left** paw down, the arrow cluster pushes the **right** paw down.  Upstream
decides this by which asset folder a key's sprite lives in (``left-keys`` has
the 55 main keys, ``right-keys`` only the four arrows), so we mirror that.

Three back-ends are available:

``win32``   Polls ``GetAsyncKeyState`` through ctypes.  Windows only, but it
            needs no third-party package.
``pynput``  Uses the ``pynput`` listener.  Cross-platform, needs ``pip install
            pynput``.
``none``    Reports nothing pressed (the cat stays idle).

Run ``python keymon.py`` to watch the detected state for a few seconds.
"""

from __future__ import annotations

import collections
import sys
import threading
import time

__all__ = ["KeyMonitor", "available_sources"]

# Virtual-key codes worth watching: letters, digits, punctuation, whitespace,
# modifiers and function keys.  Polling a curated list instead of all 256
# codes keeps the Python-side cost negligible.
_VK_CODES_ALNUM = list(range(0x30, 0x3A)) + list(range(0x41, 0x5B))
_VK_CODES_EXTRA = [
    0x08,  # backspace
    0x09,  # tab
    0x0D,  # enter
    0x10, 0x11, 0x12,  # shift, ctrl, alt
    0x14,  # caps lock
    0x1B,  # escape
    0x20,  # space
    0x21, 0x22, 0x23, 0x24,  # page up/down/end/home
    0x2C, 0x2D, 0x2E,  # print screen, insert, delete
    0x5B, 0x5C,  # windows keys
    0x60, 0x61, 0x62, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,  # numpad
    0x6A, 0x6B, 0x6D, 0x6E, 0x6F,
    0x70, 0x71, 0x72, 0x73, 0x74, 0x75,  # F1..F6
    0x76, 0x77, 0x78, 0x79, 0x7A, 0x7B,  # F7..F12
    0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF,  # ; = , - . /
    0xC0, 0xDB, 0xDC, 0xDD, 0xDE,  # ` [ \ ] '
]
# The arrow cluster drives the right paw; everything else drives the left one.
_VK_RIGHT_GROUP = frozenset((0x25, 0x26, 0x27, 0x28))
_VK_CODES = sorted(set(_VK_CODES_ALNUM + _VK_CODES_EXTRA + list(_VK_RIGHT_GROUP)))


def available_sources() -> list[str]:
    """Return the key sources usable on this machine, best first."""
    out = []
    if sys.platform == "win32":
        out.append("win32")
    try:
        import pynput  # noqa: F401
    except Exception:
        pass
    else:
        out.append("pynput")
    out.append("none")
    return out


class KeyMonitor:
    """Tracks which paw should be down, plus a smoothed keys-per-second rate."""

    def __init__(self, source: str = "auto", window: float = 2.0,
                 poll_hz: float = 50.0) -> None:
        self.window = max(0.25, float(window))
        self._events: collections.deque[float] = collections.deque()
        self._down_left = False
        self._down_right = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._source = self._pick(source)
        self._poll_hz = max(5.0, float(poll_hz))

    # -- public API --------------------------------------------------------
    @property
    def source(self) -> str:
        return self._source

    def start(self) -> None:
        if self._source == "none" or self._thread is not None:
            return
        target = (self._poll_win32 if self._source == "win32"
                  else self._listen_pynput)
        self._thread = threading.Thread(target=target, name="keymon",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def rate(self) -> float:
        """Key presses per second over the last ``window`` seconds."""
        if self._source == "none":
            return 0.0
        cutoff = time.monotonic() - self.window
        with self._lock:
            while self._events and self._events[0] < cutoff:
                self._events.popleft()
            count = len(self._events)
        return count / self.window

    def hands(self) -> tuple[bool, bool]:
        """(left_down, right_down) - the two paw parameters of the original."""
        if self._source == "none":
            return False, False
        with self._lock:
            return self._down_left, self._down_right

    def press(self, right_group: bool = False) -> None:
        with self._lock:
            self._events.append(time.monotonic())

    # -- internals ---------------------------------------------------------
    def _set_group(self, right_group: bool, pressed: bool) -> None:
        with self._lock:
            if right_group:
                self._down_right = pressed
            else:
                self._down_left = pressed

    def _pick(self, source: str) -> str:
        source = (source or "auto").lower()
        if source == "auto":
            usable = available_sources()
            return usable[0] if usable else "none"
        if source == "win32" and sys.platform != "win32":
            print("keymon: 'win32' source is Windows-only, falling back to "
                  "'none'", file=sys.stderr)
            return "none"
        if source == "pynput":
            try:
                import pynput  # noqa: F401
            except Exception:
                print("keymon: pynput is not installed (pip install pynput), "
                      "falling back to 'none'", file=sys.stderr)
                return "none"
        if source not in ("win32", "pynput", "none"):
            raise ValueError("unknown key source: %r" % source)
        return source

    def _poll_win32(self) -> None:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_state = user32.GetAsyncKeyState
        get_state.restype = ctypes.c_short
        get_state.argtypes = [ctypes.c_int]

        down: dict[int, bool] = {vk: False for vk in _VK_CODES}
        right_down: set[int] = set()
        left_down: set[int] = set()
        period = 1.0 / self._poll_hz
        next_tick = time.monotonic()
        while not self._stop.is_set():
            for vk in _VK_CODES:
                # 0x0001 == "pressed since the previous call", 0x8000 == held.
                state = get_state(vk)
                now_down = bool(state & 0x8000)
                if (state & 0x0001) or (now_down and not down[vk]):
                    self.press(vk in _VK_RIGHT_GROUP)
                down[vk] = now_down
                bucket = right_down if vk in _VK_RIGHT_GROUP else left_down
                if now_down:
                    bucket.add(vk)
                else:
                    bucket.discard(vk)
            self._down_left = bool(left_down)
            self._down_right = bool(right_down)
            next_tick += period
            sleep = next_tick - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_tick = time.monotonic()

    def _listen_pynput(self) -> None:
        from pynput import keyboard

        right_keys = {keyboard.Key.up, keyboard.Key.down,
                      keyboard.Key.left, keyboard.Key.right}
        held: set = set()

        def on_press(key) -> None:
            is_right = key in right_keys
            self.press(is_right)
            held.add(key)
            self._down_right = any(k in right_keys for k in held)
            self._down_left = any(k not in right_keys for k in held)

        def on_release(key) -> None:
            held.discard(key)
            self._down_right = any(k in right_keys for k in held)
            self._down_left = any(k not in right_keys for k in held)

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
        while not self._stop.is_set():
            time.sleep(0.1)
        listener.stop()


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="watch the detected typing rate")
    ap.add_argument("--source", default="auto",
                    help="auto | win32 | pynput | none")
    ap.add_argument("--seconds", type=float, default=10.0)
    args = ap.parse_args()

    monitor = KeyMonitor(source=args.source)
    print("source=%s  (available: %s)"
          % (monitor.source, ", ".join(available_sources())))
    print("type something (arrows move the right paw) for %.0f seconds..."
          % args.seconds)
    monitor.start()
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            left, right = monitor.hands()
            print("\r  %6.1f keys/s   paw: %s %s "
                  % (monitor.rate(),
                     "LEFT " if left else "     ",
                     "RIGHT" if right else "     "), end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()
    print("\ndone")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
