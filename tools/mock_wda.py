"""A fake WebDriverAgent for trying iMirror without an iPhone.

    python tools/mock_wda.py            # WDA on :8100, MJPEG on :9100

Draws a fake home screen, streams it as MJPEG, and draws a dot wherever a
touch lands. Typed text appears at the top. Requires PySide6.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

W, H = 390, 844  # points (iPhone 14)
SCALE = 1

state = {"touches": [], "text": "", "locked": False, "log": []}
lock = threading.Lock()


def render() -> bytes:
    img = QImage(W * SCALE, H * SCALE, QImage.Format_RGB32)
    img.fill(QColor("#1c3b6e"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(SCALE, SCALE)
    p.setPen(Qt.white)
    p.setFont(QFont("Arial", 40))
    p.drawText(QRectF(0, 60, W, 60), Qt.AlignCenter, time.strftime("%H:%M:%S"))
    p.setFont(QFont("Arial", 14))
    with lock:
        p.drawText(QRectF(10, 130, W - 20, 30), Qt.AlignCenter, "mock: " + (state["text"][-30:] or "type here"))
        if state["locked"]:
            p.drawText(QRectF(0, H / 2, W, 30), Qt.AlignCenter, "LOCKED")
        for i in range(24):
            x, y = 30 + (i % 4) * 90, 220 + (i // 4) * 95
            p.fillRect(QRectF(x, y, 60, 60), QColor.fromHsv((i * 15) % 360, 160, 230))
        for x, y in state["touches"][-40:]:
            p.setBrush(QColor(255, 255, 255, 180))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(x - 10, y - 10, 20, 20))
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPG", 70)
    return bytes(ba)


class WDA(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, value=None, status=200):
        body = json.dumps({"value": value, "sessionId": "mock"}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/status":
            self._send({"ready": True})
        elif self.path.endswith("/window/size"):
            self._send({"width": W, "height": H})
        elif self.path == "/wda/locked":
            self._send(state["locked"])
        elif self.path == "/screenshot":
            import base64

            self._send(base64.b64encode(render()).decode())
        else:
            self._send({"error": "unknown command", "message": self.path}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(length) or b"{}")
        with lock:
            state["log"].append((self.path, data))
            if self.path.endswith("/actions"):
                for step in data["actions"][0]["actions"]:
                    if step["type"] == "pointerMove":
                        state["touches"].append((step["x"], step["y"]))
            elif self.path.endswith("/wda/keys"):
                for ch in data["value"]:
                    state["text"] = state["text"][:-1] if ch == "\b" else state["text"] + ch
            elif self.path == "/wda/lock":
                state["locked"] = True
            elif self.path == "/wda/unlock":
                state["locked"] = False
            elif self.path == "/wda/homescreen":
                state["touches"].clear()
        print("POST", self.path, json.dumps(data)[:200], flush=True)
        self._send({"sessionId": "mock"} if self.path == "/session" else None)


class Mjpeg(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=--BoundaryString")
        self.end_headers()
        try:
            while True:
                frame = render()
                self.wfile.write(
                    b"--BoundaryString\r\nContent-type: image/jpg\r\nContent-Length: "
                    + str(len(frame)).encode()
                    + b"\r\n\r\n"
                    + frame
                    + b"\r\n\r\n"
                )
                time.sleep(1 / 15)
        except (BrokenPipeError, ConnectionResetError):
            pass


def serve(wda_port: int = 8100, mjpeg_port: int = 9100):
    servers = [ThreadingHTTPServer(("127.0.0.1", wda_port), WDA), ThreadingHTTPServer(("127.0.0.1", mjpeg_port), Mjpeg)]
    for s in servers:
        s.daemon_threads = True
        threading.Thread(target=s.serve_forever, daemon=True).start()
    return servers


if __name__ == "__main__":
    app = QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    serve(*(int(a) for a in sys.argv[1:3]))
    print("Mock WebDriverAgent on http://127.0.0.1:8100 (MJPEG on :9100). Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
