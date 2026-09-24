"""The host engine: samples the PC, drives the board, runs the reminders.

Everything that the GUI and the CLI have in common lives here, so the two front
ends stay thin.  The engine owns one background thread; the GUI only reads
:meth:`HostEngine.status` and writes settings.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
import socket
import threading
import time

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    serial = None
    list_ports = None

try:
    import banner as banner_mod
except ImportError:  # pragma: no cover
    banner_mod = None

try:
    import keymon
except ImportError:  # pragma: no cover
    keymon = None

PROTO_VERSION = 1

_LOOPBACK_RE = re.compile(r"^(lo|loopback)", re.IGNORECASE)
_BOARD_HINTS = re.compile(
    r"(esp32|espressif|usb\s*jtag|usb\s*serial|cdc|ch34[0-9]|cp210|silicon\s*labs)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# port helpers
# ---------------------------------------------------------------------------
def describe_ports() -> list[tuple[str, str]]:
    if list_ports is None:
        return []
    return [(p.device, p.description or "?")
            for p in sorted(list_ports.comports(), key=lambda p: p.device)]


def autodetect_port() -> str | None:
    if list_ports is None:
        return None
    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    hinted = [p for p in ports
              if _BOARD_HINTS.search("%s %s %s" % (p.device, p.description or "",
                                                   p.manufacturer or ""))]
    if hinted:
        return hinted[0].device
    return ports[0].device if ports else None


def tz_offset_minutes() -> int:
    offset = _dt.datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset else 0


def human_rate(bps: float) -> str:
    for unit, scale in (("GB/s", 1e9), ("MB/s", 1e6), ("KB/s", 1e3)):
        if bps >= scale:
            return "%.1f %s" % (bps / scale, unit)
    return "%d B/s" % int(bps)


def net_totals() -> tuple[int, int]:
    up = down = 0
    for name, io in psutil.net_io_counters(pernic=True).items():
        if _LOOPBACK_RE.match(name):
            continue
        up += io.bytes_sent
        down += io.bytes_recv
    return up, down


# ---------------------------------------------------------------------------
# sinks
# ---------------------------------------------------------------------------
class SerialSink:
    """Line-oriented link to the board, reconnecting as needed."""

    def __init__(self, port: str, baud: int, log) -> None:
        self.port = port
        self.baud = baud
        self.ser = None
        self.ready_banner: str | None = None
        self.last_heartbeat: str | None = None
        self._log = log
        self._rx = bytearray()

    @property
    def connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def open(self) -> bool:
        if serial is None:
            return False
        if self.connected:
            return True
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0,
                                     write_timeout=2)
        except Exception as exc:
            self._log("open %s failed: %s" % (self.port, exc), False)
            self.ser = None
            return False
        self._log("connected to %s @ %d" % (self.port, self.baud), True)
        self.ready_banner = None
        self._rx.clear()
        return True

    def close(self) -> None:
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def send(self, line: str) -> bool:
        if not self.connected:
            return False
        try:
            self.ser.write(line.encode("ascii", "replace") + b"\n")
            return True
        except Exception as exc:
            self._log("write failed (%s); reconnecting" % exc, False)
            self.close()
            return False

    def pump(self) -> None:
        if not self.connected:
            return
        try:
            chunk = self.ser.read(4096)
        except Exception as exc:
            self._log("read failed (%s); reconnecting" % exc, False)
            self.close()
            return
        if not chunk:
            return
        self._rx.extend(chunk)
        while b"\n" in self._rx:
            raw, _, rest = self._rx.partition(b"\n")
            self._rx = bytearray(rest)
            line = raw.decode("ascii", "replace").strip()
            if not line:
                continue
            if line.startswith("READY"):
                self.ready_banner = line
                self._log("board: %s" % line, True)
            elif line.startswith("HB"):
                self.last_heartbeat = line
            else:
                self._log("board: %s" % line, True)


class PrintSink:
    """--print-only sink: emits the protocol to stdout instead of a port."""

    def __init__(self, log) -> None:
        self.connected = True
        self.ready_banner = "READY (print-only)"
        self.last_heartbeat = None
        self._log = log

    def open(self) -> bool:
        return True

    def close(self) -> None:
        pass

    def send(self, line: str) -> bool:
        print(line)
        return True

    def pump(self) -> None:
        pass


# ---------------------------------------------------------------------------
# sampling
# ---------------------------------------------------------------------------
class Sampler:
    def __init__(self, demo: bool = False) -> None:
        self.demo = demo
        self._t0 = time.monotonic()
        self._fake = (0, 0)
        if demo or psutil is None:
            return
        psutil.cpu_percent(interval=None)
        self._last_up, self._last_down = net_totals()
        self._last_ts = time.monotonic()

    def sample(self) -> tuple[float, float, int, int]:
        if self.demo or psutil is None:
            t = time.monotonic() - self._t0
            cpu = 50.0 + 40.0 * math.sin(t / 3.0)
            mem = 55.0 + 20.0 * math.sin(t / 11.0 + 1.0)
            down = [0, 400, 9_000, 120_000, 2_400_000][int(t / 2) % 5]
            up = [0, 300, 3_000, 40_000, 500_000][int(t / 3) % 5]
            return cpu, mem, down, up

        now = time.monotonic()
        dt = max(1e-3, now - self._last_ts)
        up, down = net_totals()
        down_bps = max(0, int((down - self._last_down) / dt))
        up_bps = max(0, int((up - self._last_up) / dt))
        self._last_up, self._last_down, self._last_ts = up, down, now
        return (psutil.cpu_percent(interval=None),
                psutil.virtual_memory().percent, down_bps, up_bps)


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------
class HostEngine:
    def __init__(self, settings, sink=None, demo: bool = False,
                 on_log=None, on_notify=None) -> None:
        self.settings = settings
        self.demo = demo
        self._sink = sink
        self._on_log = on_log or (lambda msg, always=False: None)
        self._on_notify = on_notify or (lambda title, body: None)

        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._lock = threading.Lock()          # guards serial writes
        self._sampler = Sampler(demo=demo)
        self._keys = (keymon.KeyMonitor(source=settings.key_source)
                      if keymon else None)
        self._notify_watcher = None

        self._hostname = socket.gethostname()[:19]
        self._next_water = 0.0
        self._next_hello = 0.0
        self._next_reconnect = 0.0
        self._tz_min = tz_offset_minutes()
        self._tz_checked = 0.0

        self._cpu = self._mem = 0.0
        self._down = self._up = 0
        self._messages_sent = 0
        self._water_count = 0
        self.last_message = ""
        self.notify_status = ""

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        if self._keys:
            self._keys.start()
        self._reschedule_water()
        self._apply_notification_setting()
        self._thread = threading.Thread(target=self._loop, name="host-engine",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._notify_watcher:
            self._notify_watcher.stop()
            self._notify_watcher = None
        if self._keys:
            self._keys.stop()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._sink:
            self._sink.close()

    # -- logging -----------------------------------------------------------
    def _log(self, message: str, always: bool = False) -> None:
        self._on_log(message, always)

    # -- settings hooks ----------------------------------------------------
    def on_settings_changed(self) -> None:
        """Called by the GUI after the user edits anything."""
        self._reschedule_water()
        self._apply_notification_setting()
        if self._keys is not None:
            with self._lock:
                want = self.settings.key_source
            if want != self._keys.source and want != "auto":
                self._keys.stop()
                self._keys = keymon.KeyMonitor(source=want)
                self._keys.start()

    def _reschedule_water(self) -> None:
        s = self.settings
        if s.water_enabled:
            self._next_water = time.monotonic() + max(1.0, s.water_interval_min * 60.0)
        else:
            self._next_water = 0.0

    def _apply_notification_setting(self) -> None:
        want = bool(self.settings.forward_notifications)
        have = self._notify_watcher is not None
        if want and not have:
            try:
                import notify
                if not notify.available():
                    self.notify_status = notify.unavailable_reason()
                    self._log("notifications: %s" % self.notify_status, True)
                    return
                self._notify_watcher = notify.NotificationWatcher(
                    self._on_notification,
                    on_status=lambda m: self._set_notify_status(m))
                self._notify_watcher.start()
            except Exception as exc:
                self.notify_status = str(exc)
                self._log("notifications: %s" % exc, True)
        elif not want and have:
            self._notify_watcher.stop()
            self._notify_watcher = None
            self.notify_status = ""

    def _set_notify_status(self, msg: str) -> None:
        self.notify_status = msg
        self._log(msg, True)

    # -- outbound ----------------------------------------------------------
    def _send(self, line: str) -> bool:
        if not self._sink:
            return False
        with self._lock:
            return self._sink.send(line)

    def send_message(self, title: str, body: str = "", seconds: float | None = None) -> bool:
        """Render `title`/`body` and show it on the board as a banner."""
        if banner_mod is None or not banner_mod.available():
            self._log("banner: Pillow is required for messages", True)
            return False
        secs = self.settings.message_seconds if seconds is None else seconds
        try:
            img = banner_mod.render(title or "", body or "")
            line = banner_mod.encode(title or "", body or "",
                                     duration_ms=int(max(1.0, secs) * 1000))
        except Exception as exc:
            self._log("banner: render failed (%s)" % exc, True)
            return False
        self.last_message = (title + (" " + body if body else "")).strip()
        self._messages_sent += 1
        ok = self._send(line)
        if not ok:
            self._log("banner: not sent (no link)", True)
        return ok

    def clear_message(self) -> None:
        self._send("BC")

    def trigger_water_now(self) -> None:
        self._fire_water(manual=True)

    def _fire_water(self, manual: bool = False) -> None:
        s = self.settings
        title = "该喝水啦"
        body = s.water_message or "站起来喝杯水，活动一下"
        self.send_message(title, body)
        self._water_count += 1
        self._on_notify(title, body)
        if not manual:
            self._log("water reminder fired", False)

    # -- inbound from the notification watcher -----------------------------
    def _on_notification(self, app: str, body: str) -> None:
        if not self.settings.forward_notifications:
            return
        self._log("notify: %s - %s" % (app, body), False)
        self.send_message(app, body)

    # -- status for the GUI ------------------------------------------------
    def status(self) -> dict:
        left = right = False
        if self._keys is not None:
            left, right = self._keys.hands()
        next_in = None
        if self.settings.water_enabled and self._next_water:
            next_in = max(0.0, self._next_water - time.monotonic())
        connected = bool(self._sink and self._sink.connected)
        return {
            "connected": connected,
            "ready": getattr(self._sink, "ready_banner", None) if self._sink else None,
            "port": getattr(self._sink, "port", "") if self._sink else "",
            "cpu": self._cpu, "mem": self._mem,
            "down": self._down, "up": self._up,
            "keys_per_sec": self._keys.rate() if self._keys else 0.0,
            "left": left, "right": right,
            "next_water_s": next_in,
            "messages_sent": self._messages_sent,
            "water_count": self._water_count,
            "notify_status": self.notify_status,
            "last_message": self.last_message,
        }

    # -- main loop ---------------------------------------------------------
    def _loop(self) -> None:
        s = self.settings
        next_time = next_stats = next_activity = 0.0
        sent_hello = False

        # One bad tick must never take the service down: a dead engine thread
        # looks exactly like "the board stopped updating", with no clue why.
        while self._running.is_set():
            try:
                now = time.monotonic()
                sink = self._sink

                # ---- reconnect ---------------------------------------------
                if sink is not None and not sink.connected:
                    if s.autoconnect and now >= self._next_reconnect:
                        self._next_reconnect = now + 2.0
                        port = s.port or autodetect_port()
                        if port:
                            with self._lock:
                                sink.port = port
                                if sink.open():
                                    sent_hello = False
                                    next_time = next_stats = next_activity = 0.0
                if sink is not None:
                    sink.pump()

                if sink is None or not sink.connected:
                    if not s.autoconnect:
                        time.sleep(0.2)
                        continue

                # ---- handshake ---------------------------------------------
                if sink is not None and sink.connected and (
                        not sent_hello or now >= self._next_hello):
                    self._send("HELLO,%d,%s" % (PROTO_VERSION, self._hostname))
                    sent_hello = True
                    self._next_hello = now + 30.0
                    self._tz_min = tz_offset_minutes()
                    self._tz_checked = now + 60.0

                # ---- wall clock --------------------------------------------
                if now >= next_time:
                    next_time = now + 1.0
                    if now >= self._tz_checked:
                        self._tz_min = tz_offset_minutes()
                        self._tz_checked = now + 60.0
                    self._send("T,%d,%d" % (int(time.time()), self._tz_min))

                # ---- load --------------------------------------------------
                if now >= next_stats:
                    next_stats = now + max(0.2, s.stats_interval)
                    self._cpu, self._mem, self._down, self._up = \
                        self._sampler.sample()
                    self._send("S,%.1f,%.1f,%d,%d"
                               % (self._cpu, self._mem, self._down, self._up))

                # ---- paws --------------------------------------------------
                if now >= next_activity:
                    next_activity = now + 1.0 / max(1.0, s.activity_hz)
                    if self._keys is not None:
                        left, right = self._keys.hands()
                        if s.swap_paws:
                            left, right = right, left
                        self._send("K,%d,%d"
                                   % (1 if left else 0, 1 if right else 0))
                        self._send("A,%.2f" % self._keys.rate())

                # ---- water reminder ----------------------------------------
                if s.water_enabled and self._next_water and now >= self._next_water:
                    self._fire_water()
                    self._reschedule_water()
            except Exception as exc:  # keep the service alive, but say so
                self._log("engine error: %r" % (exc,), True)
                time.sleep(0.5)

            time.sleep(0.005)
