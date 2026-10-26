"""Streaming MJPEG (multipart/x-mixed-replace) reader.

WebDriverAgent serves the iPhone screen as an MJPEG stream on port 9100.
Rather than trusting multipart boundaries (WDA's are not always well formed),
frames are cut out of the byte stream by JPEG start/end markers.
"""

from __future__ import annotations

import threading
from typing import Callable, Iterable, Iterator

import requests

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
MAX_BUFFER = 8 * 1024 * 1024


def iter_jpeg_frames(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """Yield complete JPEG images found in a stream of arbitrary byte chunks."""
    buf = bytearray()
    for chunk in chunks:
        if not chunk:
            continue
        buf += chunk
        while True:
            start = buf.find(SOI)
            if start < 0:
                # Keep a trailing 0xFF in case it's the first half of a marker.
                del buf[: max(len(buf) - 1, 0)]
                break
            end = buf.find(EOI, start + 2)
            if end < 0:
                if start:
                    del buf[:start]
                if len(buf) > MAX_BUFFER:
                    buf.clear()
                break
            yield bytes(buf[start : end + 2])
            del buf[: end + 2]


class MjpegReader(threading.Thread):
    """Background thread that reads frames and hands them to a callback.

    Reconnects automatically. on_frame receives raw JPEG bytes; on_status
    receives human-readable connection state strings.
    """

    def __init__(
        self,
        url: str,
        on_frame: Callable[[bytes], None],
        on_status: Callable[[str], None] = lambda s: None,
    ):
        super().__init__(daemon=True, name="mjpeg-reader")
        self.url = url
        self.on_frame = on_frame
        self.on_status = on_status
        self._stop_event = threading.Event()
        self._response: requests.Response | None = None

    def stop(self) -> None:
        self._stop_event.set()
        resp = self._response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def run(self) -> None:
        http = requests.Session()
        http.trust_env = False
        while not self._stop_event.is_set():
            try:
                self.on_status("Connecting to screen stream…")
                with http.get(self.url, stream=True, timeout=(5, 10)) as resp:
                    resp.raise_for_status()
                    self._response = resp
                    self.on_status("Streaming")
                    for frame in iter_jpeg_frames(resp.iter_content(chunk_size=64 * 1024)):
                        if self._stop_event.is_set():
                            return
                        self.on_frame(frame)
            except Exception as exc:  # network errors, closed by stop(), etc.
                if self._stop_event.is_set():
                    return
                self.on_status(f"Stream lost ({exc.__class__.__name__}), retrying…")
            finally:
                self._response = None
            self._stop_event.wait(1.5)
