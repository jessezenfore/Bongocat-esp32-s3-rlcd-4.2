"""Forward Windows toast notifications to the board.

Uses the WinRT ``UserNotificationListener`` through the optional ``winsdk``
package.  Reading the notification centre needs the user's permission, which
Windows grants (or refuses) the first time; the watcher reports that status so
the GUI can explain itself instead of silently doing nothing.

Everything here degrades to "unavailable" rather than raising, so the rest of
the host keeps working without winsdk installed.
"""

from __future__ import annotations

import asyncio
import threading
import time

__all__ = ["NotificationWatcher", "available", "unavailable_reason"]

_state = {"checked": False, "reason": "not checked"}


def _imports():
    try:
        from winsdk.windows.ui.notifications import NotificationKinds
        from winsdk.windows.ui.notifications.management import (
            UserNotificationListener,
            UserNotificationListenerAccessStatus,
        )
    except Exception as exc:  # pragma: no cover - depends on the machine
        return None, None, None, exc
    return (UserNotificationListener, UserNotificationListenerAccessStatus,
            NotificationKinds, None)


def available() -> bool:
    listener, _, _, err = _imports()
    if err is not None or listener is None:
        _state["reason"] = "winsdk is not installed (pip install winsdk)"
        return False
    return True


def unavailable_reason() -> str:
    return _state["reason"]


def _texts(user_notification) -> tuple[str, str]:
    """(app name, body text) for a UserNotification.

    ``app_info`` hangs off the UserNotification while the text lives one level
    down in ``.notification.visual`` -- mixing the two up silently yields empty
    bodies, which is why the caller passes the outer object.
    """
    app = "通知"
    try:
        info = user_notification.app_info
        if info is not None:
            display = info.display_info
            if display is not None and display.display_name:
                app = display.display_name
    except Exception:
        pass

    parts: list[str] = []
    try:
        visual = user_notification.notification.visual
        for binding in visual.bindings:
            for element in binding.get_text_elements():
                text = (element.text or "").strip()
                if text:
                    parts.append(text)
    except Exception:
        pass

    body = " · ".join(parts) if parts else ""
    return app, body


class NotificationWatcher(threading.Thread):
    """Polls the Windows notification centre and reports new toasts."""

    def __init__(self, on_notification, on_status=None, poll_s: float = 1.5):
        super().__init__(name="notify-watch", daemon=True)
        self._on_notification = on_notification
        self._on_status = on_status or (lambda _msg: None)
        self._poll_s = poll_s
        self._stop = threading.Event()
        self.access = "unknown"

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as exc:  # pragma: no cover
            self._on_status("notifications: watcher stopped (%s)" % exc)

    async def _main(self) -> None:
        listener_cls, access_cls, kinds, err = _imports()
        if err is not None:
            self.access = "unavailable"
            self._on_status("notifications: %s" % err)
            return

        listener = listener_cls.current
        try:
            self.access = await listener.request_access_async()
        except Exception as exc:
            self.access = "error"
            self._on_status("notifications: access request failed (%s)" % exc)
            return

        if self.access != access_cls.ALLOWED:
            self._on_status(
                "notifications: Windows denied access - turn it on under "
                "设置 > 隐私和安全性 > 通知 > 允许应用访问通知")
            return

        self._on_status("notifications: watching")

        seen: dict[int, float] = {}
        first_pass = True
        while not self._stop.is_set():
            try:
                items = await listener.get_notifications_async(kinds.TOAST)
            except Exception as exc:
                self._on_status("notifications: read failed (%s)" % exc)
                return

            now = time.monotonic()
            for item in items:
                nid = item.id
                if nid in seen:
                    seen[nid] = now
                    continue
                seen[nid] = now
                if first_pass:
                    # Don't replay the backlog that was already on screen when
                    # we started; only report what arrives from now on.
                    continue
                app, body = _texts(item)
                if body:
                    self._on_notification(app, body)

            first_pass = False
            seen = {k: v for k, v in seen.items() if now - v < 300}
            await asyncio.sleep(self._poll_s)
