from imirror.gestures import Drag, GestureRecorder, Rect, Tap, fit_rect, to_device, wheel_to_swipe


def test_fit_rect_portrait_in_wide_box():
    r = fit_rect(390, 844, 1000, 844)
    assert (r.w, r.h) == (390, 844)
    assert r.x == (1000 - 390) / 2 and r.y == 0


def test_to_device_maps_and_clamps():
    view = Rect(10, 20, 195, 422)  # half scale
    assert to_device(10, 20, view, 390, 844) == (0, 0)
    assert to_device(10 + 97.5, 20 + 211, view, 390, 844) == (194.5, 421.5)
    assert to_device(9999, -50, view, 390, 844) == (389, 0)


def test_short_click_is_tap():
    g = GestureRecorder()
    g.press(100, 200, 0)
    g.move(102, 201, 30)
    assert g.release(103, 202, 80) == Tap(100, 200, 50)


def test_long_hold_is_long_press():
    g = GestureRecorder()
    g.press(100, 200, 0)
    gesture = g.release(100, 200, 900)
    assert isinstance(gesture, Tap) and gesture.hold_ms == 900


def test_drag_keeps_path_and_timing():
    g = GestureRecorder()
    g.press(200, 700, 1000)
    for i in range(1, 100):
        g.move(200, 700 - i * 6, 1000 + i * 5)
    gesture = g.release(200, 100, 1500)
    assert isinstance(gesture, Drag)
    assert gesture.path[0] == (200, 700, 0)
    assert gesture.path[-1][:2] == (200, 100)
    assert len(gesture.path) <= 24
    assert sum(dt for _, _, dt in gesture.path) == 500


def test_release_without_press():
    assert GestureRecorder().release(1, 1, 1) is None


def test_wheel_up_swipes_down():
    x1, y1, x2, y2 = wheel_to_swipe(100, 400, 120, 844)
    assert x1 == x2 == 100 and y2 > y1
    assert wheel_to_swipe(100, 800, -1200, 844)[3] >= 1
