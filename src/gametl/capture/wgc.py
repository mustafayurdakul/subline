"""Windows Graphics Capture of one window, through the `windows-capture`
package.

Frames arrive on the library's own thread as zero-copy BGRA views that are
valid only inside the callback, so the BGR part is copied out at once. Only
the newest frame is kept: a consumer that falls behind skips frames instead
of queueing them.

Three capture options need a newer Windows than capture itself, and the
library refuses to start when one is asked for on a system without it. Each
option the system turns down is left to the system's default and the
capture starts again (`dropped_options` names them). For the user:
- the cursor (Windows 10 2004 and later can leave it out): on older builds
  it can show in the frames, so OCR may see it over the text;
- the capture border (only Windows 11 can hide it): on Windows 10, Windows
  draws a coloured frame round the captured game while a session runs;
- the minimum update interval (Windows 11 24H2 and later): before that the
  system sends a frame each time the game draws one, and the frame handler
  copies at most one per interval, so the CPU cost stays the same.
"""

from __future__ import annotations

import threading
import time

from windows_capture import WindowsCapture

from .base import Frame

# The library's refusal to start with an option this Windows lacks, and the
# words of it that name each option (matched in lower case).
_UNSUPPORTED = "is not supported by the graphics capture api"
_OPTION_WORDS = {
    "cursor_capture": "cursor capture",
    "draw_border": "border",
    "minimum_update_interval": "minimum update interval",
}
# What each option does, for the status line when this Windows lacks it.
OPTION_LABELS = {
    "cursor_capture": "hiding the cursor",
    "draw_border": "hiding the capture border",
    "minimum_update_interval": "capping the frame rate",
}


def _refused_option(error: Exception, options: dict[str, object]) -> str | None:
    """The option a failed start says this Windows lacks, when it is one
    still asked for; None for any other error."""
    message = str(error).lower()
    if _UNSUPPORTED not in message:
        return None
    return next(
        (name for name, words in _OPTION_WORDS.items() if words in message and options[name] is not None),
        None,
    )


class WgcWindowCapture:
    """Capture one window by HWND. Use as a context manager, or call
    `start()` and `stop()`."""

    def __init__(self, hwnd: int, min_interval_ms: int | None = None) -> None:
        self.hwnd = hwnd
        self._min_interval_ms = min_interval_ms
        self.dropped_options: list[str] = []  # capture options this Windows lacks, left to its default

        self._frame_ready = threading.Condition()
        self._latest: Frame | None = None
        self._consumed = 0  # frames_received at the last next_frame() return
        self._closed = False
        self._control = None
        self._throttle_s = 0.0  # the interval the frame handler keeps when the system cannot
        self._last_copy: float | None = None
        self.frames_received = 0

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> WgcWindowCapture:
        """Start capturing. An option this Windows lacks is dropped and the
        start tried again; every retry drops one more option, so there are
        three at most. Any other error is raised."""
        options: dict[str, object] = {
            "cursor_capture": False,  # the cursor is not text
            "draw_border": False,  # no yellow capture frame around the game
            "minimum_update_interval": self._min_interval_ms,
        }
        while True:
            try:
                self._control = self._new_capture(options).start_free_threaded()
                break
            except Exception as exc:
                refused = _refused_option(exc, options)
                if refused is None:
                    raise
                # None is the system's default, which the library does not check for.
                options[refused] = None
                self.dropped_options.append(refused)
        if options["minimum_update_interval"] is None and self._min_interval_ms:
            self._throttle_s = self._min_interval_ms / 1000.0
        return self

    def _new_capture(self, options: dict[str, object]) -> WindowsCapture:
        """A capture session with `options` and this object's frame and close
        handlers (a session that failed to start is not used again)."""
        capture = WindowsCapture(**options, window_hwnd=self.hwnd)

        @capture.event
        def on_frame_arrived(frame, capture_control):
            now = time.perf_counter()
            if self._throttle_s and self._last_copy is not None and now - self._last_copy < self._throttle_s:
                return  # too soon: a game keeps drawing, so a newer frame follows
            self._last_copy = now
            # frame.frame_buffer is HxWx4 BGRA, zero-copy, valid only here.
            image = frame.frame_buffer[:, :, :3].copy()
            received = Frame(image=image, timestamp=now)
            with self._frame_ready:
                self._latest = received
                self.frames_received += 1
                self._frame_ready.notify_all()

        @capture.event
        def on_closed():
            with self._frame_ready:
                self._closed = True
                self._frame_ready.notify_all()

        return capture

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
        """True once the target window went away or the capture thread
        ended. An error in the frame handler ends the thread without a close
        event; `stop()` raises it."""
        control = self._control
        return self._closed or (control is not None and control.is_finished())

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
