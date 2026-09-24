"""Bongo Cat host - desktop GUI with a tray icon.

    python host/gui.py            # or the packaged BongoCat.exe

Everything the firmware needs is driven from here: the serial link, the
drink-water reminder, and messages pushed to the board's screen.  Closing the
window can drop to the system tray so it keeps running in the background.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import APP_NAME, Settings, config_path, default_settings  # noqa: E402
from engine import (HostEngine, SerialSink, autodetect_port,  # noqa: E402
                    describe_ports, human_rate)

APP_TITLE = "Bongo Cat 桌面监视器"


def _tray_image():
    """A tiny cat face for the notification area."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([6, 12, 58, 56], fill=(255, 255, 255, 255),
              outline=(20, 20, 20, 255), width=3)
    d.polygon([(12, 22), (10, 4), (26, 14)], fill=(255, 255, 255, 255),
              outline=(20, 20, 20, 255))
    d.polygon([(52, 22), (54, 4), (38, 14)], fill=(255, 255, 255, 255),
              outline=(20, 20, 20, 255))
    d.ellipse([20, 28, 27, 35], fill=(20, 20, 20, 255))
    d.ellipse([37, 28, 44, 35], fill=(20, 20, 20, 255))
    d.arc([26, 32, 38, 44], start=20, end=160, fill=(20, 20, 20, 255), width=2)
    return img


class App:
    def __init__(self, settings: Settings, start_hidden: bool = False) -> None:
        self.settings = settings
        self.engine: HostEngine | None = None
        self.tray = None
        self._hidden = False

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.minsize(560, 640)
        try:
            self.root.iconphoto(True, tk.PhotoImage(width=1, height=1))
        except Exception:
            pass

        self._log_lines: list[str] = []
        self._build_ui()
        self._start_engine()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(400, self._tick)

        if start_hidden:
            self.root.after(200, self._hide_to_tray)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 3}
        root = self.root
        root.columnconfigure(0, weight=1)

        style = ttk.Style()
        try:
            style.configure("Hint.TLabel", foreground="#666")
            style.configure("Ok.TLabel", foreground="#137333")
            style.configure("Bad.TLabel", foreground="#b00020")
        except Exception:
            pass

        # ---- connection ---------------------------------------------------
        conn = ttk.LabelFrame(root, text="连接")
        conn.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        conn.columnconfigure(1, weight=1)

        ttk.Label(conn, text="串口").grid(row=0, column=0, sticky="w", **pad)
        self.port_var = tk.StringVar(value=self.settings.port or "自动检测")
        self.port_box = ttk.Combobox(conn, textvariable=self.port_var,
                                     state="readonly", width=28)
        self.port_box.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(conn, text="刷新", command=self._refresh_ports).grid(
            row=0, column=2, **pad)

        self.autoconnect_var = tk.BooleanVar(value=self.settings.autoconnect)
        ttk.Checkbutton(conn, text="自动连接并断线重连",
                        variable=self.autoconnect_var,
                        command=self._apply).grid(row=1, column=0, columnspan=3,
                                                  sticky="w", **pad)

        self.conn_state = ttk.Label(conn, text="● 未连接", style="Bad.TLabel")
        self.conn_state.grid(row=2, column=0, columnspan=3, sticky="w", **pad)

        # ---- cat ----------------------------------------------------------
        cat = ttk.LabelFrame(root, text="猫爪")
        cat.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        self.swap_var = tk.BooleanVar(value=self.settings.swap_paws)
        ttk.Checkbutton(cat, text="交换左右手（主键盘 → 右爪，方向键 → 左爪）",
                        variable=self.swap_var,
                        command=self._apply).grid(row=0, column=0, sticky="w",
                                                  **pad)
        self.paw_label = ttk.Label(cat, text="爪子: --", style="Hint.TLabel")
        self.paw_label.grid(row=1, column=0, sticky="w", **pad)

        # ---- water --------------------------------------------------------
        water = ttk.LabelFrame(root, text="喝水提醒")
        water.grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        water.columnconfigure(3, weight=1)

        self.water_var = tk.BooleanVar(value=self.settings.water_enabled)
        ttk.Checkbutton(water, text="启用", variable=self.water_var,
                        command=self._apply).grid(row=0, column=0, sticky="w",
                                                  **pad)
        ttk.Label(water, text="每").grid(row=0, column=1, sticky="e", **pad)
        self.water_min_var = tk.StringVar(value=str(self.settings.water_interval_min))
        ttk.Spinbox(water, from_=1, to=600, increment=5, width=6,
                    textvariable=self.water_min_var,
                    command=self._apply).grid(row=0, column=2, **pad)
        ttk.Label(water, text="分钟提醒一次").grid(row=0, column=3, sticky="w",
                                                   **pad)

        ttk.Label(water, text="提醒内容").grid(row=1, column=0, sticky="w", **pad)
        self.water_msg_var = tk.StringVar(value=self.settings.water_message)
        e = ttk.Entry(water, textvariable=self.water_msg_var)
        e.grid(row=1, column=1, columnspan=3, sticky="ew", **pad)
        e.bind("<FocusOut>", lambda _e: self._apply())
        e.bind("<Return>", lambda _e: self._apply())

        self.water_toast_var = tk.BooleanVar(value=self.settings.water_toast)
        ttk.Checkbutton(water, text="同时弹出桌面通知", variable=self.water_toast_var,
                        command=self._apply).grid(row=2, column=0, columnspan=2,
                                                  sticky="w", **pad)
        ttk.Button(water, text="立即测试", command=self._test_water).grid(
            row=2, column=3, sticky="e", **pad)

        self.water_state = ttk.Label(water, text="", style="Hint.TLabel")
        self.water_state.grid(row=3, column=0, columnspan=4, sticky="w", **pad)

        # ---- messages -----------------------------------------------------
        msg = ttk.LabelFrame(root, text="电脑消息")
        msg.grid(row=3, column=0, sticky="ew", padx=10, pady=4)
        msg.columnconfigure(1, weight=1)

        self.fwd_var = tk.BooleanVar(value=self.settings.forward_notifications)
        ttk.Checkbutton(msg, text="把 Windows 通知转发到屏幕",
                        variable=self.fwd_var, command=self._apply).grid(
            row=0, column=0, columnspan=2, sticky="w", **pad)
        self.notify_state = ttk.Label(msg, text="", style="Hint.TLabel",
                                      wraplength=500, justify="left")
        self.notify_state.grid(row=1, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(msg, text="显示时长").grid(row=2, column=0, sticky="w", **pad)
        self.dur_var = tk.StringVar(value=str(self.settings.message_seconds))
        ttk.Spinbox(msg, from_=2, to=120, increment=1, width=6,
                    textvariable=self.dur_var, command=self._apply).grid(
            row=2, column=1, sticky="w", **pad)

        ttk.Label(msg, text="标题").grid(row=3, column=0, sticky="w", **pad)
        self.msg_title_var = tk.StringVar(value="")
        ttk.Entry(msg, textvariable=self.msg_title_var).grid(
            row=3, column=1, sticky="ew", **pad)

        ttk.Label(msg, text="内容").grid(row=4, column=0, sticky="w", **pad)
        self.msg_body_var = tk.StringVar(value="")
        body_entry = ttk.Entry(msg, textvariable=self.msg_body_var)
        body_entry.grid(row=4, column=1, sticky="ew", **pad)
        body_entry.bind("<Return>", lambda _e: self._send_message())

        btns = ttk.Frame(msg)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Button(btns, text="发送到屏幕", command=self._send_message).pack(
            side="left")
        ttk.Button(btns, text="清除", command=self._clear_message).pack(
            side="left", padx=6)
        self.msg_state = ttk.Label(btns, text="", style="Hint.TLabel")
        self.msg_state.pack(side="left", padx=8)

        # ---- background ---------------------------------------------------
        bg = ttk.LabelFrame(root, text="后台运行")
        bg.grid(row=4, column=0, sticky="ew", padx=10, pady=4)
        self.tray_var = tk.BooleanVar(value=self.settings.close_to_tray)
        ttk.Checkbutton(bg, text="关闭窗口时最小化到托盘（继续在后台运行）",
                        variable=self.tray_var, command=self._apply).grid(
            row=0, column=0, sticky="w", **pad)
        row = ttk.Frame(bg)
        row.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Button(row, text="最小化到托盘", command=self._hide_to_tray).pack(
            side="left")
        ttk.Button(row, text="打开配置文件夹",
                   command=self._open_config_dir).pack(side="left", padx=6)

        # ---- status + log -------------------------------------------------
        stat = ttk.LabelFrame(root, text="状态")
        stat.grid(row=5, column=0, sticky="ew", padx=10, pady=4)
        stat.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(stat, text="--", justify="left")
        self.status_label.grid(row=0, column=0, sticky="w", **pad)

        logf = ttk.LabelFrame(root, text="日志")
        logf.grid(row=6, column=0, sticky="nsew", padx=10, pady=(4, 10))
        logf.columnconfigure(0, weight=1)
        logf.rowconfigure(0, weight=1)
        root.rowconfigure(6, weight=1)
        self.log_text = tk.Text(logf, height=8, wrap="none", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        sb = ttk.Scrollbar(logf, command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 8))
        self.log_text.configure(yscrollcommand=sb.set)

        self._refresh_ports()

    # -------------------------------------------------------------- engine
    def _start_engine(self) -> None:
        port = self._selected_port()
        sink = SerialSink(port or "", self.settings.baud, self._log)
        self.engine = HostEngine(self.settings, sink=sink,
                                 on_log=self._log, on_notify=self._toast)
        self.engine.start()
        self._log("就绪。串口: %s" % (port or "自动检测"), True)

    def _selected_port(self) -> str:
        value = self.port_var.get()
        return "" if value in ("自动检测", "") else value

    def _refresh_ports(self) -> None:
        ports = describe_ports()
        values = ["自动检测"] + ["%s  %s" % (dev, desc) for dev, desc in ports]
        self.port_box.configure(values=values)
        current = self.settings.port
        match = next((v for v in values[1:] if current and v.startswith(current)),
                     None)
        self.port_var.set(match or "自动检测")
        if self.engine and self.engine._sink is not None:
            self.engine._sink.port = self._selected_port() or self.engine._sink.port

    def _apply(self) -> None:
        s = self.settings
        s.port = self._selected_port()
        s.autoconnect = bool(self.autoconnect_var.get())
        s.swap_paws = bool(self.swap_var.get())
        s.water_enabled = bool(self.water_var.get())
        s.water_toast = bool(self.water_toast_var.get())
        s.forward_notifications = bool(self.fwd_var.get())
        s.close_to_tray = bool(self.tray_var.get())
        try:
            s.water_interval_min = max(1.0, float(self.water_min_var.get()))
        except ValueError:
            pass
        try:
            s.message_seconds = max(1.0, float(self.dur_var.get()))
        except ValueError:
            pass
        s.water_message = self.water_msg_var.get().strip() or s.water_message
        s.save()
        if self.engine:
            self.engine._sink.port = s.port or self.engine._sink.port
            self.engine.on_settings_changed()

    # ------------------------------------------------------------ actions
    def _test_water(self) -> None:
        self._apply()
        if self.engine:
            self.engine.trigger_water_now()
            self.msg_state.configure(text="已发送提醒")

    def _send_message(self) -> None:
        title = self.msg_title_var.get().strip()
        body = self.msg_body_var.get().strip()
        if not title and not body:
            self.msg_state.configure(text="请输入内容")
            return
        if self.engine and self.engine.send_message(title, body):
            self.msg_state.configure(text="已发送")
            self.msg_body_var.set("")
        else:
            self.msg_state.configure(text="发送失败（检查串口连接）")

    def _clear_message(self) -> None:
        if self.engine:
            self.engine.clear_message()
            self.msg_state.configure(text="已清除")

    def _open_config_dir(self) -> None:
        d = os.path.dirname(config_path())
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)  # noqa: S606 - Windows shell open
        except Exception:
            messagebox.showinfo(APP_TITLE, "配置目录：\n%s" % d)

    # --------------------------------------------------------------- tray
    def _hide_to_tray(self) -> None:
        self.root.withdraw()
        self._hidden = True
        if self.tray is None:
            self._start_tray()

    def _show_window(self) -> None:
        self._hidden = False
        self.root.after(0, self._do_show)

    def _do_show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _start_tray(self) -> None:
        try:
            import pystray
        except ImportError:
            self._log("托盘不可用（未安装 pystray），窗口保持显示", True)
            self._do_show()
            return

        image = _tray_image()
        if image is None:
            self._log("托盘图标不可用（未安装 Pillow）", True)
            self._do_show()
            return

        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", lambda *_: self._show_window(),
                             default=True),
            pystray.MenuItem("立即提醒喝水",
                             lambda *_: self.root.after(0, self._test_water)),
            pystray.MenuItem("发送测试消息",
                             lambda *_: self.root.after(0, self._tray_test_msg)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda *_: self.root.after(0, self._quit)),
        )
        self.tray = pystray.Icon(APP_NAME, image, APP_TITLE, menu)
        threading.Thread(target=self.tray.run, name="tray", daemon=True).start()
        self._log("已最小化到托盘，双击图标可恢复窗口", True)

    def _tray_test_msg(self) -> None:
        if self.engine:
            self.engine.send_message("Bongo Cat", "托盘菜单测试消息")

    def _toast(self, title: str, message: str) -> None:
        """Desktop notification, used by the water reminder."""
        if not self.settings.water_toast:
            return
        if self.tray is not None:
            try:
                self.tray.notify(message, title)
                return
            except Exception:
                pass
        self._log("提醒: %s - %s" % (title, message), True)

    # --------------------------------------------------------------- misc
    def _log(self, message: str, always: bool = False) -> None:
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), message)
        self._log_lines.append(line)
        if len(self._log_lines) > 500:
            del self._log_lines[:200]
        try:
            self.root.after(0, self._append_log, line)
        except Exception:
            pass

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        if self.tray_var.get():
            self._hide_to_tray()
        else:
            self._quit()

    def _quit(self) -> None:
        try:
            if self.engine:
                self.engine.stop()
            if self.tray is not None:
                self.tray.stop()
            self._apply()          # persist whatever the UI currently shows
        except Exception:
            pass
        self.root.destroy()

    # --------------------------------------------------------------- tick
    def _tick(self) -> None:
        if self.engine is None:
            return
        st = self.engine.status()

        if st["connected"]:
            txt = "● 已连接  %s" % (st["ready"] or "等待握手")
            self.conn_state.configure(text=txt, style="Ok.TLabel")
        else:
            self.conn_state.configure(text="● 未连接（等待串口）", style="Bad.TLabel")

        self.status_label.configure(text=(
            "CPU %.1f%%   RAM %.1f%%   网速 ↓%s ↑%s   按键 %.1f/s\n"
            "已发送消息 %d 条   已提醒喝水 %d 次   下次提醒: %s"
            % (st["cpu"], st["mem"], human_rate(st["down"]),
               human_rate(st["up"]), st["keys_per_sec"],
               st["messages_sent"], st["water_count"],
               ("%.0f 分钟后" % (st["next_water_s"] / 60.0))
               if st["next_water_s"] is not None else "未启用")))

        self.paw_label.configure(text="爪子: 左 %s   右 %s%s"
                                 % ("按下" if st["left"] else "抬起",
                                    "按下" if st["right"] else "抬起",
                                    "   (已交换)" if self.settings.swap_paws else ""))

        if self.settings.water_enabled and st["next_water_s"] is not None:
            self.water_state.configure(
                text="下次提醒还有 %.0f 分钟" % (st["next_water_s"] / 60.0))
        else:
            self.water_state.configure(text="未启用")

        if self.settings.forward_notifications:
            self.notify_state.configure(
                text=st["notify_status"] or "正在启动通知监听…")
        else:
            self.notify_state.configure(text="未开启")

        self.root.after(500, self._tick)


def _install_crash_log() -> str:
    """Windowed builds have no console, so send tracebacks to a file."""
    import traceback
    path = os.path.join(os.path.dirname(config_path()), "error.log")

    def hook(exc_type, exc, tb):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n=== %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                traceback.print_exception(exc_type, exc, tb, file=fh)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=APP_TITLE)
    ap.add_argument("--minimised", action="store_true",
                    help="start hidden in the tray")
    ap.add_argument("--port", default=None, help="preselect a serial port")
    args = ap.parse_args(argv)

    crash_log = _install_crash_log()

    settings = default_settings()
    if args.port:
        settings.port = args.port
    if args.minimised:
        settings.start_minimised = True

    try:
        app = App(settings, start_hidden=args.minimised or settings.start_minimised)
    except Exception:
        _install_crash_log()
        import traceback
        with open(crash_log, "a", encoding="utf-8") as fh:
            fh.write("\n=== %s startup failed ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            traceback.print_exc(file=fh)
        raise
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
