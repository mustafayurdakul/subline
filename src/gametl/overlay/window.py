"""The overlay: a transparent, click-through, always-on-top window glued to
the game window, drawing translations at frame-pixel positions through a
BlockPainter (overlay/paint.py).

Coordinates: the app runs with Qt's high-DPI scaling disabled and the
process set to Per-Monitor-V2 DPI awareness, so widget coordinates are
physical pixels and capture-frame pixel (x, y) lands at overlay pixel (x, y).
"""

from __future__ import annotations

import ctypes
import traceback
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from ..capture.windows import foreground_window, is_minimized, is_window, window_rect
from ..geometry import Box
from .paint import BlockPainter, RenderBlock

_user32 = ctypes.windll.user32
_GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
_WDA_NONE = 0x00000000
_WDA_EXCLUDEFROMCAPTURE = 0x00000011
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
_user32.SetWindowLongW.restype = ctypes.c_long
_user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.SetWindowDisplayAffinity.restype = wintypes.BOOL


class OverlayWindow(QWidget):
    target_lost = Signal()

    def __init__(
        self,
        target_hwnd: int,
        hide_when_unfocused: bool = True,
        exclude_from_capture: bool = True,
        font_family: str = "Segoe UI",
        poll_ms: int = 33,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self.target_hwnd = target_hwnd
        self.hide_when_unfocused = hide_when_unfocused
        self.exclude_from_capture = exclude_from_capture
        self.painter = BlockPainter(font_family)
        self.paint_errors = 0

        self._blocks: list[RenderBlock] = []
        self._target_rect: Box | None = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._follow)
        self._poll_ms = poll_ms

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self._follow()
        self.show()
        self._apply_native_styles()
        self._timer.start(self._poll_ms)

    def _apply_native_styles(self) -> None:
        """Make sure the Win32 extended styles say click-through, no
        activation and no taskbar entry, whatever a Qt version maps the
        window flags to."""
        hwnd = wintypes.HWND(int(self.winId()))
        ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        wanted = ex | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        if wanted != ex:
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, wanted)
        self._set_capture_affinity()

    def _set_capture_affinity(self) -> None:
        affinity = _WDA_EXCLUDEFROMCAPTURE if self.exclude_from_capture else _WDA_NONE
        _user32.SetWindowDisplayAffinity(wintypes.HWND(int(self.winId())), affinity)

    def apply(self, font_family: str, hide_when_unfocused: bool, exclude_from_capture: bool) -> None:
        """Settings edited while the overlay runs."""
        self.hide_when_unfocused = hide_when_unfocused
        if exclude_from_capture != self.exclude_from_capture:
            self.exclude_from_capture = exclude_from_capture
            self._set_capture_affinity()
        if font_family != self.painter.font_family:
            self.painter.set_font(font_family)
            self.update()

    def ex_style(self) -> int:
        return _user32.GetWindowLongW(wintypes.HWND(int(self.winId())), _GWL_EXSTYLE)

    def _follow(self) -> None:
        hwnd = self.target_hwnd
        if not is_window(hwnd):
            self._timer.stop()
            self.target_lost.emit()
            return
        rect = window_rect(hwnd)
        if rect != self._target_rect:
            self._target_rect = rect
            self.setGeometry(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
        visible = not is_minimized(hwnd)
        if visible and self.hide_when_unfocused:
            visible = foreground_window() in (hwnd, int(self.winId()))
        if visible != self.isVisible():
            self.setVisible(visible)

    @property
    def target_rect(self) -> Box | None:
        return self._target_rect

    # -- content ---------------------------------------------------------------

    @Slot(list)
    def set_blocks(self, blocks: list[RenderBlock]) -> None:
        self._blocks = list(blocks)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        try:
            self.painter.paint_blocks(painter, self._blocks)
        except Exception:
            # A paint bug must never leave the painter open: Qt faults later if it does.
            self.paint_errors += 1
            if self.paint_errors <= 3:
                traceback.print_exc()
        finally:
            painter.end()
