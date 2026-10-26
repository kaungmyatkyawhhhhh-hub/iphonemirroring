"""Persistent user settings, stored as JSON in the per-user app data folder."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "iMirror"


CONFIG_PATH = _config_dir() / "settings.json"


@dataclass
class Settings:
    # Where WebDriverAgent is reachable. With a USB tunnel this is localhost.
    wda_host: str = "127.0.0.1"
    wda_port: int = 8100
    mjpeg_port: int = 9100

    # Stream tuning (applied to WebDriverAgent's MJPEG server).
    framerate: int = 30
    jpeg_quality: int = 60
    scaling_percent: int = 50

    # Optional helper commands started before connecting. Empty = don't start.
    # {wda_port}/{mjpeg_port} are substituted.
    tunnel_command: str = ""
    wda_launch_command: str = ""

    # AirPlay (view-only) mode.
    uxplay_path: str = ""
    airplay_name: str = "iMirror"

    always_on_top: bool = False

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Settings":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @property
    def wda_url(self) -> str:
        return f"http://{self.wda_host}:{self.wda_port}"

    @property
    def mjpeg_url(self) -> str:
        return f"http://{self.wda_host}:{self.mjpeg_port}"
