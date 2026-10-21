"""Windows Graphics Capture of a single window, via the `windows-capture`
package (Rust bindings).

Frames arrive on the library's own thread. We copy the BGR part out of the
zero-copy BGRA view immediately (the native buffer is only valid inside the
callback) and keep just the newest frame; consumers that fall behind skip
frames instead of queueing them.
"""

from __future__ import annotations

import threading
import time

from windows_capture import WindowsCapture

from .base import Frame
from .windows import window_rect


class WgcWindowCapture:
    """Capture one window by HWND. Use as a context manager or call
    start()/stop()."""

    def __init__(
        self,
        hwnd: int,
        min_interval_ms: int | None = None,
        capture_cursor: bool = False,
        draw_border: bool = False,
    ) -> None:
        self.hwnd = hwnd
        self._min_interval_ms = min_interval_ms
        self._capture_cursor = capture_cursor
        self._draw_border = draw_border

        self._lock = threading.Condition()
        self._latest: Frame | None = None
        self._seq = 0  # increments per received frame
        self._consumed_seq = 0
        self._closed = False
        self._control = None
        self.frames_received = 0

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> "WgcWindowCapture":
        capture = WindowsCapture(
            cursor_capture=self._capture_cursor,
            draw_border=self._draw_border,
            minimum_update_interval=self._min_interval_ms,
            window_hwnd=self.hwnd,
        )

        @capture.event
        def on_frame_arrived(frame, capture_control):  # noqa: ANN001
            # frame.frame_buffer is HxWx4 BGRA, zero-copy, valid only here.
            image = frame.frame_buffer[:, :, :3].copy()
            f = Frame(image=image, timestamp=time.perf_counter(), window_rect=window_rect(self.hwnd))
            with self._lock:
                self._latest = f
                self._seq += 1
                self.frames_received += 1
                self._lock.notify_all()

        @capture.event
        def on_closed():
            with self._lock:
                self._closed = True
                self._lock.notify_all()

        self._control = capture.start_free_threaded()
        return self

    def stop(self) -> None:
        if self._control is not None:
            try:
                self._control.stop()
            finally:
                self._control = None

    def __enter__(self) -> "WgcWindowCapture":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- frames --------------------------------------------------------------

    @property
    def closed(self) -> bool:
        """True once the target window went away."""
        return self._closed

    def latest(self) -> Frame | None:
        """Newest frame, or None if nothing arrived yet. Does not block and
        does not mark the frame as consumed."""
        with self._lock:
            return self._latest

    def next_frame(self, timeout: float | None = None) -> Frame | None:
        """Block until a frame newer than the last one returned by this method
        arrives, then return it. Returns None on timeout or if the capture
        closed. Intermediate frames are skipped."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            while self._seq == self._consumed_seq and not self._closed:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._lock.wait(remaining)
            if self._seq == self._consumed_seq:
                return None
            self._consumed_seq = self._seq
            return self._latest
