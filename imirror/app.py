"""iMirror main window: shows the iPhone screen and forwards mouse/keyboard input."""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QToolBar,
    QWidget,
)

from imirror import __version__
from imirror.config import Settings
from imirror.gestures import Drag, GestureRecorder, Rect, Tap, fit_rect, to_device, wheel_to_swipe
from imirror.helpers import LOG_DIR, ProcessGroup, find_uxplay, split_commands, uxplay_command
from imirror.mjpeg import MjpegReader
from imirror.wda import Size, WDAClient, WDAError


class DeviceBridge(QObject):
    """Runs every WebDriverAgent call on one background thread, in order."""

    connected = Signal(object)  # Size
    failed = Signal(str)
    status = Signal(str)
    frame = Signal(QImage)
    screenshot = Signal(bytes)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.client = WDAClient(settings.wda_url)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wda")
        self._reader: MjpegReader | None = None
        self.size: Size | None = None

    def submit(self, fn: Callable, *args) -> None:
        def run():
            try:
                fn(*args)
            except WDAError as exc:
                self.status.emit(str(exc))
            except Exception as exc:  # never let the worker die silently
                self.status.emit(f"Error: {exc}")

        self._pool.submit(run)

    def connect_device(self, wait_seconds: float = 45.0) -> None:
        self.submit(self._connect, wait_seconds)

    def _connect(self, wait_seconds: float) -> None:
        s = self.settings
        self.client = WDAClient(s.wda_url)
        deadline = time.monotonic() + wait_seconds
        last_error = ""
        while True:
            try:
                self.status.emit(f"Waiting for WebDriverAgent at {s.wda_url}…")
                self.client.status()
                break
            except WDAError as exc:
                last_error = str(exc)
                if time.monotonic() > deadline:
                    self.failed.emit(last_error)
                    return
                time.sleep(1.5)
        try:
            self.client.start_session()
            self.client.configure_stream(s.framerate, s.jpeg_quality, s.scaling_percent)
            self.size = self.client.window_size()
        except WDAError as exc:
            self.failed.emit(str(exc))
            return
        self.connected.emit(self.size)
        self._start_stream()

    def _start_stream(self) -> None:
        self.stop_stream()

        def on_frame(data: bytes) -> None:
            img = QImage.fromData(data, "JPG")
            if not img.isNull():
                self.frame.emit(img)

        self._reader = MjpegReader(self.settings.mjpeg_url, on_frame, self.status.emit)
        self._reader.start()

    def stop_stream(self) -> None:
        if self._reader:
            self._reader.stop()
            self._reader.join(timeout=3)
            self._reader = None

    def refresh_size(self) -> None:
        def run():
            self.size = self.client.window_size()

        self.submit(run)

    def take_screenshot(self) -> None:
        self.submit(lambda: self.screenshot.emit(self.client.screenshot_png()))

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.stop_stream()


class ScreenView(QWidget):
    """Draws the phone and translates input into touches."""

    def __init__(self, bridge: DeviceBridge):
        super().__init__()
        self.bridge = bridge
        self.image: QImage | None = None
        self.message = "Not connected.\nClick “Connect” to start mirroring."
        self.recorder = GestureRecorder()
        self._pending_text = ""
        self._type_timer = QTimer(self, singleShot=True, interval=120, timeout=self._flush_text)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(False)
        self.setMinimumSize(240, 420)
        bridge.frame.connect(self.set_frame)

    # ---- geometry --------------------------------------------------------

    BEZEL = 14.0

    def _screen_rect(self) -> Rect:
        if self.image is not None:
            cw, ch = self.image.width(), self.image.height()
        elif self.bridge.size:
            cw, ch = self.bridge.size.width, self.bridge.size.height
        else:
            cw, ch = 9.0, 19.5
        b = self.BEZEL
        r = fit_rect(cw, ch, self.width() - 2 * b, self.height() - 2 * b)
        return Rect(r.x + b, r.y + b, r.w, r.h)

    def _device_size(self) -> tuple[float, float] | None:
        size = self.bridge.size
        if not size:
            return None
        w, h = size.width, size.height
        # Follow rotation: if the stream orientation differs, swap.
        if self.image is not None and (self.image.width() > self.image.height()) != (w > h):
            w, h = h, w
        return w, h

    def _to_device(self, pos: QPointF) -> tuple[float, float] | None:
        dev = self._device_size()
        if not dev:
            return None
        return to_device(pos.x(), pos.y(), self._screen_rect(), *dev)

    # ---- painting --------------------------------------------------------

    def set_frame(self, img: QImage) -> None:
        rotated = self.image is not None and (img.width() > img.height()) != (
            self.image.width() > self.image.height()
        )
        self.image = img
        if rotated:
            self.bridge.refresh_size()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#1e1f22"))

        r = self._screen_rect()
        screen = QRectF(r.x, r.y, r.w, r.h)
        radius = min(r.w, r.h) * 0.11
        b = self.BEZEL

        body = QPainterPath()
        body.addRoundedRect(screen.adjusted(-b, -b, b, b), radius + b * 0.8, radius + b * 0.8)
        p.fillPath(body, QColor("#0b0b0c"))
        p.setPen(QPen(QColor("#4a4b50"), 2))
        p.drawPath(body)

        clip = QPainterPath()
        clip.addRoundedRect(screen, radius, radius)
        p.setClipPath(clip)
        if self.image is not None:
            p.drawImage(screen, self.image)
        else:
            p.fillRect(screen, QColor("#000000"))
            p.setPen(QColor("#c8c8c8"))
            p.drawText(screen.adjusted(16, 16, -16, -16), Qt.AlignCenter | Qt.TextWordWrap, self.message)
        p.end()

    def sizeHint(self) -> QSize:
        return QSize(400, 820)

    # ---- mouse → touch ---------------------------------------------------

    def _inside(self, pos: QPointF) -> bool:
        return self._screen_rect().contains(pos.x(), pos.y())

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.LeftButton or not self._inside(e.position()):
            return
        pt = self._to_device(e.position())
        if pt:
            self.recorder.press(*pt, time.monotonic() * 1000)

    def mouseMoveEvent(self, e) -> None:
        pt = self._to_device(e.position())
        if pt:
            self.recorder.move(*pt, time.monotonic() * 1000)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        pt = self._to_device(e.position())
        if not pt:
            return
        gesture = self.recorder.release(*pt, time.monotonic() * 1000)
        client = self.bridge.client
        if isinstance(gesture, Tap):
            self.bridge.submit(client.tap, gesture.x, gesture.y, gesture.hold_ms)
        elif isinstance(gesture, Drag):
            self.bridge.submit(client.drag_path, gesture.path)

    def wheelEvent(self, e) -> None:
        dev = self._device_size()
        pt = self._to_device(e.position())
        if not dev or not pt or not self._inside(e.position()):
            return
        x1, y1, x2, y2 = wheel_to_swipe(pt[0], pt[1], e.angleDelta().y(), dev[1])
        if abs(y2 - y1) > 2:
            self.bridge.submit(self.bridge.client.swipe, x1, y1, x2, y2, 120)

    # ---- keyboard → typing ----------------------------------------------

    def keyPressEvent(self, e) -> None:
        if e.matches(QKeySequence.Paste):
            self._queue_text(QGuiApplication.clipboard().text())
            return
        key = e.key()
        if key == Qt.Key_Backspace:
            self._queue_text("\b")
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._queue_text("\n")
        elif key == Qt.Key_Tab:
            self._queue_text("\t")
        elif e.text() and e.text().isprintable() and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            self._queue_text(e.text())
        else:
            super().keyPressEvent(e)

    def _queue_text(self, text: str) -> None:
        if not self.bridge.size:
            return
        self._pending_text += text
        self._type_timer.start()

    def _flush_text(self) -> None:
        text, self._pending_text = self._pending_text, ""
        if text:
            self.bridge.submit(self.bridge.client.type_text, text)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("iMirror settings")
        self.settings = settings
        form = QFormLayout(self)

        self.host = QLineEdit(settings.wda_host)
        self.port = self._spin(settings.wda_port, 1, 65535)
        self.mjpeg = self._spin(settings.mjpeg_port, 1, 65535)
        self.fps = self._spin(settings.framerate, 1, 60)
        self.quality = self._spin(settings.jpeg_quality, 1, 100)
        self.scale = self._spin(settings.scaling_percent, 10, 100)
        self.tunnel = QPlainTextEdit(settings.tunnel_command)
        self.tunnel.setPlaceholderText("e.g. iproxy {wda_port} 8100 && iproxy {mjpeg_port} 9100")
        self.tunnel.setFixedHeight(56)
        self.launch = QPlainTextEdit(settings.wda_launch_command)
        self.launch.setPlaceholderText("e.g. ios runwda --bundleid=com.facebook.WebDriverAgentRunner.xctrunner")
        self.launch.setFixedHeight(56)
        self.uxplay = QLineEdit(settings.uxplay_path)
        self.uxplay.setPlaceholderText("auto-detect uxplay.exe")
        self.airplay_name = QLineEdit(settings.airplay_name)

        form.addRow("WebDriverAgent host", self.host)
        form.addRow("WebDriverAgent port", self.port)
        form.addRow("Screen stream port", self.mjpeg)
        form.addRow("Frame rate", self.fps)
        form.addRow("JPEG quality (%)", self.quality)
        form.addRow("Stream scale (%)", self.scale)
        form.addRow("USB tunnel command", self.tunnel)
        form.addRow("Launch WDA command", self.launch)
        form.addRow("UxPlay path", self.uxplay)
        form.addRow("AirPlay name", self.airplay_name)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _spin(value: int, lo: int, hi: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(lo, hi)
        box.setValue(value)
        return box

    def accept(self) -> None:
        s = self.settings
        s.wda_host = self.host.text().strip() or "127.0.0.1"
        s.wda_port = self.port.value()
        s.mjpeg_port = self.mjpeg.value()
        s.framerate = self.fps.value()
        s.jpeg_quality = self.quality.value()
        s.scaling_percent = self.scale.value()
        s.tunnel_command = self.tunnel.toPlainText().strip()
        s.wda_launch_command = self.launch.toPlainText().strip()
        s.uxplay_path = self.uxplay.text().strip()
        s.airplay_name = self.airplay_name.text().strip() or "iMirror"
        s.save()
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.helpers = ProcessGroup()
        self.airplay = ProcessGroup()
        self.bridge = DeviceBridge(settings)
        self.view = ScreenView(self.bridge)
        self.setCentralWidget(self.view)
        self.setWindowTitle("iMirror")
        self._build_toolbar()
        self.statusBar().showMessage("Ready")

        self.bridge.status.connect(self.statusBar().showMessage)
        self.bridge.connected.connect(self._on_connected)
        self.bridge.failed.connect(self._on_failed)
        self.bridge.screenshot.connect(self._save_screenshot)

        self._watchdog = QTimer(self, interval=2000, timeout=self._check_helpers)
        self._watchdog.start()

        if settings.always_on_top:
            self.pin_action.setChecked(True)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Controls", movable=False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.TopToolBarArea, tb)
        menu = self.menuBar().addMenu("&iMirror")

        def act(target, text: str, slot, shortcut: str | None = None, tip: str = "") -> QAction:
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setToolTip(f"{tip or text}" + (f"  ({shortcut})" if shortcut else ""))
            target.addAction(a)
            return a

        self.connect_action = act(tb, "Connect", self.connect_device, "Ctrl+K", "Connect over USB / Wi-Fi via WebDriverAgent")
        menu.addAction(self.connect_action)
        tb.addSeparator()
        act(tb, "Home", lambda: self.bridge.submit(self.bridge.client.home), "Ctrl+H")
        act(tb, "Apps", lambda: self.bridge.submit(self.bridge.client.app_switcher), "Ctrl+Tab", "App switcher")
        act(tb, "Lock", self._toggle_lock, "Ctrl+L", "Lock / unlock")
        act(tb, "Vol−", lambda: self.bridge.submit(self.bridge.client.press_button, "volumeDown"), "Ctrl+Down")
        act(tb, "Vol+", lambda: self.bridge.submit(self.bridge.client.press_button, "volumeUp"), "Ctrl+Up")
        act(tb, "Shot", self.bridge.take_screenshot, "Ctrl+S", "Save a full-resolution screenshot")

        self.airplay_action = act(menu, "AirPlay receiver (view only)", self.toggle_airplay, "Ctrl+P")
        self.airplay_action.setCheckable(True)
        self.pin_action = act(menu, "Keep on top", self._toggle_pin, "Ctrl+T")
        self.pin_action.setCheckable(True)
        menu.addSeparator()
        act(menu, "Settings…", self.open_settings, "Ctrl+,")
        act(menu, "Help", self.show_help, "F1")
        menu.addSeparator()
        act(menu, "Quit", self.close, "Ctrl+Q")

    # ---- connection ------------------------------------------------------

    def connect_device(self) -> None:
        s = self.settings
        self.bridge.stop_stream()
        self.helpers.stop_all()
        values = {"wda_port": s.wda_port, "mjpeg_port": s.mjpeg_port}
        try:
            for argv in split_commands(s.tunnel_command, **values):
                self.helpers.start(argv, "tunnel")
            for argv in split_commands(s.wda_launch_command, **values):
                self.helpers.start(argv, "wda")
        except (OSError, ValueError, KeyError) as exc:
            self._on_failed(f"Could not start helper command: {exc}")
            return
        self.connect_action.setEnabled(False)
        self.view.message = "Connecting to your iPhone…"
        self.view.update()
        self.bridge.connect_device()

    def _on_connected(self, size: Size) -> None:
        self.connect_action.setEnabled(True)
        self.connect_action.setText("Reconnect")
        self.statusBar().showMessage(f"Connected — screen {size.width:.0f}×{size.height:.0f} pt")
        self.view.setFocus()

    def _on_failed(self, message: str) -> None:
        self.connect_action.setEnabled(True)
        self.view.message = "Could not connect.\nSee the status bar, or press F1 for setup help."
        self.view.update()
        self.statusBar().showMessage(message)
        QMessageBox.warning(
            self,
            "iMirror",
            f"{message}\n\nMake sure WebDriverAgent is running on the iPhone and its ports are "
            f"forwarded (see Help). Helper logs: {LOG_DIR}",
        )

    def _check_helpers(self) -> None:
        dead = self.helpers.any_exited()
        if dead is not None:
            self.helpers.procs.remove(dead)
            self.statusBar().showMessage(
                f"Helper '{Path(dead.args[0]).name}' exited (code {dead.returncode}). Logs: {LOG_DIR}"
            )
        dead = self.airplay.any_exited()
        if dead is not None:
            self.airplay.procs.remove(dead)
            self.airplay_action.setChecked(False)
            self.statusBar().showMessage(f"AirPlay receiver stopped (code {dead.returncode}). Log: {LOG_DIR / 'uxplay.log'}")

    # ---- actions ---------------------------------------------------------

    def _toggle_lock(self) -> None:
        c = self.bridge.client

        def run():
            c.unlock() if c.is_locked() else c.lock()

        self.bridge.submit(run)

    def toggle_airplay(self, on: bool) -> None:
        if not on:
            self.airplay.stop_all()
            self.statusBar().showMessage("AirPlay receiver stopped")
            return
        exe = find_uxplay(self.settings.uxplay_path)
        if not exe:
            self.airplay_action.setChecked(False)
            QMessageBox.information(
                self,
                "AirPlay receiver not found",
                "AirPlay mode uses UxPlay, an open-source AirPlay receiver.\n\n"
                "Install UxPlay for Windows (see README), or set its path in Settings.",
            )
            return
        try:
            self.airplay.start(uxplay_command(exe, self.settings.airplay_name), "uxplay")
        except OSError as exc:
            self.airplay_action.setChecked(False)
            QMessageBox.warning(self, "iMirror", f"Could not start UxPlay: {exc}")
            return
        self.statusBar().showMessage(
            f"AirPlay ready: on the iPhone open Control Center → Screen Mirroring → “{self.settings.airplay_name}”"
        )

    def _toggle_pin(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()
        self.settings.always_on_top = on
        self.settings.save()

    def _save_screenshot(self, png: bytes) -> None:
        default = Path.home() / "Pictures" / f"iPhone {datetime.now():%Y-%m-%d %H.%M.%S}.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", str(default), "PNG image (*.png)")
        if path:
            Path(path).write_bytes(png)
            self.statusBar().showMessage(f"Saved {path}")

    def open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec():
            self.statusBar().showMessage("Settings saved — click Connect to apply")

    def show_help(self) -> None:
        QMessageBox.information(
            self,
            f"iMirror {__version__}",
            "Two ways to mirror:\n\n"
            "1. Full control (USB or Wi-Fi) — needs WebDriverAgent installed on the iPhone once.\n"
            "   Click Connect. Mouse = touch, drag = swipe, hold = long-press, wheel = scroll,\n"
            "   typing goes to the focused text field, Ctrl+V pastes.\n\n"
            "2. View only (wireless AirPlay) — iMirror menu → AirPlay receiver, then on the iPhone:\n"
            "   Control Center → Screen Mirroring → pick this PC.\n\n"
            "Full setup steps are in README.md.",
        )

    def closeEvent(self, e) -> None:
        self.bridge.shutdown()
        self.helpers.stop_all()
        self.airplay.stop_all()
        super().closeEvent(e)


def main(argv: list[str] | None = None) -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("iMirror")
    win = MainWindow(Settings.load())
    win.resize(win.view.sizeHint().width(), win.view.sizeHint().height() + 60)
    win.show()
    return app.exec()
