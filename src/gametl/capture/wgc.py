"""Windows Graphics Capture of one window, through the `windows-capture`
package.

Frames arrive on the library's own thread as zero-copy BGRA views that are
valid only inside the callback, so the BGR part is copied out at once. Only
the newest frame is kept: a consumer that falls behind skips frames instead
of queueing them.
"""

from __future__ import annotations

import threading
import time

from windows_capture import WindowsCapture

from .base import Frame
from .windows import window_rect


class WgcWindowCapture:
    """Capture one window by HWND. Use as a context manager, or call
    `start()` and `stop()`."""

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

        self._frame_ready = threading.Condition()
        self._latest: Frame | None = None
        self._consumed = 0  # frames_received at the last next_frame() return
        self._closed = False
        self._control = None
        self.frames_received = 0

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> WgcWindowCapture:
        capture = WindowsCapture(
            cursor_capture=self._capture_cursor,
            draw_border=self._draw_border,
            minimum_update_interval=self._min_interval_ms,
            window_hwnd=self.hwnd,
        )

        @capture.event
        def on_frame_arrived(frame, capture_control):
            # frame.frame_buffer is HxWx4 BGRA, zero-copy, valid only here.
            image = frame.frame_buffer[:, :, :3].copy()
            received = Frame(image=image, timestamp=time.perf_counter(), window_rect=window_rect(self.hwnd))
            with self._frame_ready:
                self._latest = received
                self.frames_received += 1
                self._frame_ready.notify_all()

        @capture.event
        def on_closed():
            with self._frame_ready:
                self._closed = True
                self._frame_ready.notify_all()

        self._control = capture.start_free_threaded()
        return self

    def stop(self) -> None:
        if self._control is not None:
            try:
                self._control.stop()
            finally:
                self._control = None

    def __enter__(self) -> WgcWindowCapture:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- frames --------------------------------------------------------------

    @property
    def closed(self) -> bool:
        """True once the target window went away."""
        return self._closed

    def next_frame(self, timeout: float | None = None) -> Frame | None:
        """Block until a frame newer than the last one returned arrives, then
        return it; frames in between are skipped. None on timeout or once the
        capture has closed."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._frame_ready:
            while self.frames_received == self._consumed and not self._closed:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._frame_ready.wait(remaining)
            if self.frames_received == self._consumed:
                return None
            self._consumed = self.frames_received
            return self._latest
