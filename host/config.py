"""Persisted settings for the Bongo Cat host application.

Stored as JSON under ``%APPDATA%/BongoCat-RLCD/config.json`` so the GUI, the CLI
and the packaged exe all share one configuration.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from dataclasses import dataclass, field

APP_NAME = "BongoCat-RLCD"


def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


@dataclass
class Settings:
    # ---- connection -------------------------------------------------------
    port: str = ""                 # "" = auto-detect
    baud: int = 115200
    autoconnect: bool = True
    stats_interval: float = 1.0
    activity_hz: float = 20.0
    key_source: str = "auto"

    # ---- what the board shows --------------------------------------------
    # Swapping paws sends the two hand flags the other way round, so the main
    # keyboard drives the right paw and the arrow keys drive the left one.
    swap_paws: bool = False

    # ---- drink-water reminder --------------------------------------------
    water_enabled: bool = True
    water_interval_min: float = 45.0
    water_message: str = "该喝水啦，站起来活动一下"
    water_toast: bool = True       # also raise a desktop notification

    # ---- messages on the board -------------------------------------------
    message_seconds: float = 8.0   # how long a banner stays up
    forward_notifications: bool = False

    # ---- window / tray ----------------------------------------------------
    close_to_tray: bool = True
    start_minimised: bool = False

    # ---- misc -------------------------------------------------------------
    verbose: bool = False

    # ------------------------------------------------------------------
    def to_json(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Settings":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def load(self) -> "Settings":
        try:
            with open(config_path(), "r", encoding="utf-8") as fh:
                merged = self.from_json(json.load(fh))
        except Exception:
            return self
        # keep this instance so callers holding a reference see the values
        for f in dataclasses.fields(self):
            setattr(self, f.name, getattr(merged, f.name))
        return self

    def save(self) -> None:
        os.makedirs(config_dir(), exist_ok=True)
        tmp = config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.to_json(), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, config_path())


def default_settings() -> Settings:
    return Settings().load()
