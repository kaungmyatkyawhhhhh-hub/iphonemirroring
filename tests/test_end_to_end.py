"""Drives the real window against tools/mock_wda.py (offscreen Qt)."""

import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import mock_wda  # noqa: E402
from imirror.app import MainWindow  # noqa: E402
from imirror.config import Settings  # noqa: E402


def wait_until(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_connect_stream_tap_and_type(app, tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "save", lambda self, path=None: None)
    servers = mock_wda.serve(18100, 19100)
    try:
        win = MainWindow(Settings(wda_port=18100, mjpeg_port=19100))
        win.resize(400, 880)
        win.show()
        win.connect_device()
        view = win.view
        assert wait_until(lambda: view.image is not None), win.statusBar().currentMessage()

        # Click the centre of the screen -> tap at the centre in device points.
        r = view._screen_rect()
        centre = QPoint(int(r.x + r.w / 2), int(r.y + r.h / 2))
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, centre)
        assert wait_until(lambda: any(p.endswith("/actions") for p, _ in mock_wda.state["log"]))
        path, body = next((p, b) for p, b in mock_wda.state["log"] if p.endswith("/actions"))
        first = body["actions"][0]["actions"][0]
        assert abs(first["x"] - 195) < 3 and abs(first["y"] - 422) < 3

        view.setFocus()
        QTest.keyClicks(view, "hi!")
        QTest.keyClick(view, Qt.Key_Backspace)
        assert wait_until(lambda: mock_wda.state["text"] == "hi")

        win.close()
    finally:
        for s in servers:
            s.shutdown()
