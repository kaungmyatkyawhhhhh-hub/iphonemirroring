"""Turn mouse input on the mirrored screen into iPhone touch gestures.

Kept free of Qt so it can be unit-tested.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

TAP_MAX_MOVE = 8.0  # points; anything further is a drag
LONG_PRESS_MS = 450
SAMPLE_MIN_DIST = 6.0  # points between recorded drag samples


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


def fit_rect(content_w: float, content_h: float, box_w: float, box_h: float) -> Rect:
    """Largest rect with the content's aspect ratio centred inside the box."""
    if content_w <= 0 or content_h <= 0 or box_w <= 0 or box_h <= 0:
        return Rect(0, 0, 0, 0)
    scale = min(box_w / content_w, box_h / content_h)
    w, h = content_w * scale, content_h * scale
    return Rect((box_w - w) / 2, (box_h - h) / 2, w, h)


def to_device(px: float, py: float, view: Rect, device_w: float, device_h: float) -> tuple[float, float]:
    """Map a widget pixel inside the displayed frame to device points (clamped)."""
    fx = (px - view.x) / view.w if view.w else 0.0
    fy = (py - view.y) / view.h if view.h else 0.0
    fx = min(max(fx, 0.0), 1.0)
    fy = min(max(fy, 0.0), 1.0)
    return round(fx * (device_w - 1), 1), round(fy * (device_h - 1), 1)


@dataclass
class Tap:
    x: float
    y: float
    hold_ms: int


@dataclass
class Drag:
    # (x, y, ms since previous sample); first sample has 0.
    path: list[tuple[float, float, int]]


@dataclass
class GestureRecorder:
    """Records one press→move→release sequence (device points, ms timestamps)."""

    samples: list[tuple[float, float, float]] = field(default_factory=list)

    def press(self, x: float, y: float, t_ms: float) -> None:
        self.samples = [(x, y, t_ms)]

    def move(self, x: float, y: float, t_ms: float) -> None:
        if not self.samples:
            return
        lx, ly, _ = self.samples[-1]
        if math.hypot(x - lx, y - ly) >= SAMPLE_MIN_DIST:
            self.samples.append((x, y, t_ms))

    def release(self, x: float, y: float, t_ms: float) -> Tap | Drag | None:
        if not self.samples:
            return None
        sx, sy, st = self.samples[0]
        lx, ly, _ = self.samples[-1]
        if (x, y) != (lx, ly):
            self.samples.append((x, y, t_ms))
        samples, self.samples = self.samples, []

        far = max(math.hypot(px - sx, py - sy) for px, py, _ in samples)
        if far <= TAP_MAX_MOVE:
            held = int(t_ms - st)
            return Tap(sx, sy, held if held >= LONG_PRESS_MS else 50)

        path: list[tuple[float, float, int]] = []
        prev_t = st
        for px, py, pt in samples:
            path.append((px, py, int(pt - prev_t)))
            prev_t = pt
        path = _simplify(path)
        return Drag(path)


def _simplify(path: list[tuple[float, float, int]], max_points: int = 24) -> list[tuple[float, float, int]]:
    """Merge samples so we never send a huge action chain, preserving total time."""
    if len(path) <= max_points:
        return path
    step = (len(path) - 1) / (max_points - 1)
    keep = sorted({round(i * step) for i in range(max_points)})
    out: list[tuple[float, float, int]] = []
    acc = 0
    ki = 0
    for i, (x, y, dt) in enumerate(path):
        acc += dt
        if ki < len(keep) and i == keep[ki]:
            out.append((x, y, acc if out else 0))
            acc = 0
            ki += 1
    return out


def wheel_to_swipe(x: float, y: float, delta_y: float, device_h: float) -> tuple[float, float, float, float]:
    """Mouse wheel → short swipe. Positive delta (wheel up) scrolls content down."""
    distance = max(min(delta_y / 120.0, 3.0), -3.0) * device_h * 0.12
    y2 = min(max(y + distance, 1.0), device_h - 2.0)
    return x, y, x, y2
