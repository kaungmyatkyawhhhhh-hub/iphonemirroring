"""Minimal client for WebDriverAgent (appium/WebDriverAgent) running on the iPhone.

WebDriverAgent is the XCUITest-based server that exposes the device over HTTP:
touch injection, hardware buttons, typing, and an MJPEG screen stream.
All coordinates here are in iOS *points* (not pixels).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import requests


class WDAError(RuntimeError):
    pass


@dataclass
class Size:
    width: float
    height: float


class WDAClient:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session_id: str | None = None
        self._http = requests.Session()
        # Never route localhost traffic through a system proxy.
        self._http.trust_env = False

    # ---- low level -------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict | None = None, timeout: float | None = None):
        url = f"{self.base_url}{path}"
        try:
            resp = self._http.request(method, url, json=payload, timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            raise WDAError(f"Cannot reach WebDriverAgent at {self.base_url}: {exc}") from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        value = body.get("value") if isinstance(body, dict) else None
        if resp.status_code >= 400 or (isinstance(value, dict) and "error" in value):
            message = value.get("message") if isinstance(value, dict) else resp.text
            raise WDAError(f"{method} {path} failed ({resp.status_code}): {message}")
        return body

    def _session_path(self, path: str) -> str:
        if not self.session_id:
            self.start_session()
        return f"/session/{self.session_id}{path}"

    # ---- session ---------------------------------------------------------

    def status(self) -> dict:
        return self._request("GET", "/status", timeout=5)

    def start_session(self) -> str:
        body = self._request("POST", "/session", {"capabilities": {"alwaysMatch": {}}})
        value = body.get("value") or {}
        sid = body.get("sessionId") or value.get("sessionId")
        if not sid:
            raise WDAError("WebDriverAgent did not return a session id")
        self.session_id = sid
        return sid

    def configure_stream(self, framerate: int, quality: int, scaling_percent: int) -> None:
        self._request(
            "POST",
            self._session_path("/appium/settings"),
            {
                "settings": {
                    "mjpegServerFramerate": framerate,
                    "mjpegServerScreenshotQuality": quality,
                    "mjpegScalingFactor": scaling_percent,
                }
            },
        )

    def window_size(self) -> Size:
        value = self._request("GET", self._session_path("/window/size"))["value"]
        return Size(float(value["width"]), float(value["height"]))

    # ---- touch -----------------------------------------------------------

    def _pointer(self, steps: list[dict]) -> None:
        actions = {
            "actions": [
                {
                    "type": "pointer",
                    "id": "finger1",
                    "parameters": {"pointerType": "touch"},
                    "actions": steps,
                }
            ]
        }
        self._request("POST", self._session_path("/actions"), actions)

    def tap(self, x: float, y: float, hold_ms: int = 50) -> None:
        self._pointer(
            [
                {"type": "pointerMove", "duration": 0, "x": x, "y": y},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": hold_ms},
                {"type": "pointerUp", "button": 0},
            ]
        )

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 250, hold_ms: int = 0) -> None:
        steps = [
            {"type": "pointerMove", "duration": 0, "x": x1, "y": y1},
            {"type": "pointerDown", "button": 0},
        ]
        if hold_ms:
            steps.append({"type": "pause", "duration": hold_ms})
        steps += [
            {"type": "pointerMove", "duration": max(duration_ms, 1), "x": x2, "y": y2},
            {"type": "pointerUp", "button": 0},
        ]
        self._pointer(steps)

    def drag_path(self, points: list[tuple[float, float, int]]) -> None:
        """Replay a recorded finger path: [(x, y, ms_since_previous), ...]."""
        if not points:
            return
        x0, y0, _ = points[0]
        steps = [
            {"type": "pointerMove", "duration": 0, "x": x0, "y": y0},
            {"type": "pointerDown", "button": 0},
        ]
        for x, y, dt in points[1:]:
            steps.append({"type": "pointerMove", "duration": max(int(dt), 1), "x": x, "y": y})
        steps.append({"type": "pointerUp", "button": 0})
        self._pointer(steps)

    # ---- buttons & keyboard ---------------------------------------------

    def home(self) -> None:
        self._request("POST", "/wda/homescreen")

    def press_button(self, name: str) -> None:
        """name: 'home', 'volumeUp' or 'volumeDown'."""
        self._request("POST", self._session_path("/wda/pressButton"), {"name": name})

    def lock(self) -> None:
        self._request("POST", "/wda/lock")

    def unlock(self) -> None:
        self._request("POST", "/wda/unlock")

    def is_locked(self) -> bool:
        return bool(self._request("GET", "/wda/locked").get("value"))

    def type_text(self, text: str) -> None:
        if text:
            self._request("POST", self._session_path("/wda/keys"), {"value": list(text)})

    def app_switcher(self) -> None:
        size = self.window_size()
        cx = size.width / 2
        # Slow swipe up from the very bottom edge, with a pause mid-screen.
        self._pointer(
            [
                {"type": "pointerMove", "duration": 0, "x": cx, "y": size.height - 1},
                {"type": "pointerDown", "button": 0},
                {"type": "pointerMove", "duration": 400, "x": cx, "y": size.height * 0.6},
                {"type": "pause", "duration": 600},
                {"type": "pointerUp", "button": 0},
            ]
        )

    def screenshot_png(self) -> bytes:
        value = self._request("GET", "/screenshot", timeout=30)["value"]
        return base64.b64decode(value)
