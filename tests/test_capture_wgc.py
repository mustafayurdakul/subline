"""Window capture start-up: options this Windows lacks are dropped and the
start retried, the frame handler keeps the frame rate when the system
cannot, and a capture thread that ends without a close event counts as
closed. A fake WindowsCapture stands in for the library."""

from __future__ import annotations

import numpy as np
import pytest

from gametl.capture import wgc
from gametl.capture.wgc import WgcWindowCapture

# The library's own refusals, in the order it checks the options.
REFUSALS = {
    "cursor_capture": "Toggling cursor capture is not supported by the Graphics Capture API on this platform.",
    "draw_border": "Toggling the capture border is not supported by the Graphics Capture API on this platform.",
    "minimum_update_interval": (
        "Setting a minimum update interval is not supported by the Graphics Capture API on this platform."
    ),
}


class FakeControl:
    def __init__(self) -> None:
        self.finished = False
        self.stopped = False

    def is_finished(self) -> bool:
        return self.finished

    def stop(self) -> None:
        self.stopped = True


class FakeWindowsCapture:
    """Refuses the options in `lacking` as the library does on an older
    Windows, or fails with `error`."""

    lacking: set[str] = set()
    error: str | None = None
    made: list[FakeWindowsCapture] = []

    def __init__(self, **options) -> None:
        self.options = options
        self.frame_handler = None
        self.closed_handler = None
        self.control: FakeControl | None = None
        FakeWindowsCapture.made.append(self)

    def event(self, handler):
        if handler.__name__ == "on_frame_arrived":
            self.frame_handler = handler
        else:
            self.closed_handler = handler
        return handler

    def start_free_threaded(self) -> FakeControl:
        assert self.frame_handler is not None and self.closed_handler is not None
        if self.error is not None:
            raise Exception(f"Capture session threw an exception: {self.error}")
        for name, refusal in REFUSALS.items():
            if name in self.lacking and self.options[name] is not None:
                raise Exception(f"Capture session threw an exception: Graphics capture API error: {refusal}")
        self.control = FakeControl()
        return self.control


class FakeFrame:
    def __init__(self, value: int) -> None:
        self.frame_buffer = np.full((2, 3, 4), value, dtype=np.uint8)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> type[FakeWindowsCapture]:
    monkeypatch.setattr(FakeWindowsCapture, "lacking", set())
    monkeypatch.setattr(FakeWindowsCapture, "error", None)
    monkeypatch.setattr(FakeWindowsCapture, "made", [])
    monkeypatch.setattr(wgc, "WindowsCapture", FakeWindowsCapture)
    return FakeWindowsCapture


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The frame handler's clock: the test sets now[0]."""
    now = [100.0]
    monkeypatch.setattr(wgc.time, "perf_counter", lambda: now[0])
    return now


def test_a_new_windows_takes_every_option_at_once(fake) -> None:
    cap = WgcWindowCapture(0x1234, min_interval_ms=100).start()
    assert len(fake.made) == 1
    assert fake.made[0].options == {
        "cursor_capture": False,
        "draw_border": False,
        "minimum_update_interval": 100,
        "window_hwnd": 0x1234,
    }
    assert cap.dropped_options == []


def test_options_an_older_windows_lacks_fall_back_to_its_default(fake) -> None:
    fake.lacking = {"cursor_capture", "draw_border", "minimum_update_interval"}  # Windows 10 1903
    cap = WgcWindowCapture(0x1234, min_interval_ms=100).start()
    assert len(fake.made) == 4  # one more start per refused option
    assert cap.dropped_options == ["cursor_capture", "draw_border", "minimum_update_interval"]
    last = fake.made[-1].options
    # None explicitly: the library's own default for the cursor is True, which it would check.
    assert last["cursor_capture"] is None and last["draw_border"] is None
    assert last["minimum_update_interval"] is None
    assert all(made.frame_handler is not None for made in fake.made)  # each session got its own handlers


def test_windows_10_keeps_the_options_it_has(fake) -> None:
    fake.lacking = {"draw_border", "minimum_update_interval"}  # Windows 10 22H2
    cap = WgcWindowCapture(0x1234, min_interval_ms=100).start()
    assert cap.dropped_options == ["draw_border", "minimum_update_interval"]
    assert fake.made[-1].options["cursor_capture"] is False


def test_any_other_start_error_is_raised_without_a_retry(fake) -> None:
    fake.error = "Failed to create Direct3D device"
    with pytest.raises(Exception, match="Direct3D"):
        WgcWindowCapture(0x1234, min_interval_ms=100).start()
    assert len(fake.made) == 1


def test_without_the_system_interval_the_handler_copies_one_frame_per_interval(fake, clock) -> None:
    fake.lacking = {"minimum_update_interval"}
    cap = WgcWindowCapture(0x1234, min_interval_ms=100).start()
    handler = fake.made[-1].frame_handler
    for t, value in ((100.0, 1), (100.04, 2), (100.09, 3), (100.11, 4), (100.15, 5), (100.22, 6)):
        clock[0] = t
        handler(FakeFrame(value), None)
    assert cap.frames_received == 3  # at 100.0, 100.11 and 100.22
    frame = cap.next_frame(timeout=0)
    assert frame is not None and int(frame.image[0, 0, 0]) == 6 and frame.image.shape == (2, 3, 3)


def test_with_the_system_interval_every_frame_is_copied(fake, clock) -> None:
    cap = WgcWindowCapture(0x1234, min_interval_ms=100).start()
    handler = fake.made[-1].frame_handler
    for t in (100.0, 100.01, 100.02):
        clock[0] = t
        handler(FakeFrame(1), None)
    assert cap.frames_received == 3


def test_a_capture_thread_that_ended_without_a_close_event_counts_as_closed(fake) -> None:
    cap = WgcWindowCapture(0x1234).start()
    assert not cap.closed
    fake.made[-1].control.finished = True  # a frame-handler error ends the thread, no on_closed
    assert cap.closed
    cap.stop()
    assert fake.made[-1].control.stopped


def test_the_close_event_marks_the_capture_closed(fake) -> None:
    cap = WgcWindowCapture(0x1234).start()
    fake.made[-1].closed_handler()
    assert cap.closed
    assert cap.next_frame(timeout=0) is None
