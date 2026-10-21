"""The overlay: a transparent, click-through, always-on-top window glued to
the game window, drawing translated blocks at frame-pixel positions.

Coordinates: the app runs with Qt's high-DPI scaling disabled and the process
set to Per-Monitor-V2 DPI awareness, so widget coordinates are physical
pixels and a capture-frame pixel (x, y) lands at overlay pixel (x, y).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

from PySide6.QtCore import QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..capture.windows import foreground_window, is_minimized, is_window, window_rect

Box = tuple[int, int, int, int]
RGB = tuple[int, int, int]

_user32 = ctypes.windll.user32
_GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
_WDA_EXCLUDEFROMCAPTURE = 0x00000011
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
_user32.SetWindowLongW.restype = ctypes.c_long
_user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.SetWindowDisplayAffinity.restype = wintypes.BOOL


@dataclass(slots=True)
class RenderBlock:
    """One thing to draw: a box in frame pixels with text lines."""

    bbox: Box
    lines: list[str] = field(default_factory=list)
    bg: RGB = (0, 0, 0)
    fg: RGB = (255, 255, 255)
    align: str = "center"  # "center" | "left"
    outline: bool = False  # debug: draw the box outline only


class OverlayWindow(QWidget):
    target_lost = Signal()

    def __init__(
        self,
        target_hwnd: int,
        hide_when_unfocused: bool = True,
        exclude_from_capture: bool = True,
        font_family: str = "Segoe UI",
        padding: int = 3,
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
        self.font_family = font_family
        self.padding = padding
        self.excluded_from_capture = False

        self._blocks: list[RenderBlock] = []
        self._target_rect: Box | None = None
        self._font_cache: dict[tuple, QFont] = {}

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
        """Belt and braces: make sure the Win32 extended styles say
        click-through, no activation, no taskbar entry, even if a Qt version
        maps the window flags differently."""
        hwnd = wintypes.HWND(int(self.winId()))
        ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        wanted = ex | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        if wanted != ex:
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, wanted)
        if self.exclude_from_capture:
            self.excluded_from_capture = bool(_user32.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE))

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

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for block in self._blocks:
            self._paint_block(painter, block)
        painter.end()

    def _paint_block(self, p: QPainter, block: RenderBlock) -> None:
        x0, y0, x1, y1 = block.bbox
        pad = self.padding
        # OCR boxes hug the glyphs; widen sideways by a share of the line
        # height so the first and last glyphs of the original are covered too.
        pad_x = max(pad, int(0.2 * (y1 - y0)))
        rect = QRect(x0 - pad_x, y0 - pad, (x1 - x0) + 2 * pad_x, (y1 - y0) + 2 * pad)
        if block.outline:
            p.setPen(QPen(QColor(0, 255, 0), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
            return
        p.fillRect(rect, QColor(*block.bg))
        if not block.lines:
            return
        font = self.fit_font(block.lines, x1 - x0, y1 - y0)
        p.setFont(font)
        p.setPen(QColor(*block.fg))
        n = len(block.lines)
        line_h = (y1 - y0) / n
        h_align = Qt.AlignmentFlag.AlignHCenter if block.align == "center" else Qt.AlignmentFlag.AlignLeft
        for i, line in enumerate(block.lines):
            r = QRect(x0, int(y0 + i * line_h), x1 - x0, int(line_h) + 1)
            p.drawText(r, Qt.AlignmentFlag.AlignVCenter | h_align, line)

    def fit_font(self, lines: list[str], width: int, height: int) -> QFont:
        """Largest pixel size at which every line fits the width, starting
        from 80 % of the per-line height."""
        key = (tuple(lines), width, height)
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        n = max(1, len(lines))
        font = QFont(self.font_family)
        lo, hi = 6, max(6, int(height / n * 0.8))
        while lo < hi:
            mid = (lo + hi + 1) // 2
            font.setPixelSize(mid)
            widest = max(QFontMetrics(font).horizontalAdvance(line) for line in lines)
            if widest <= width:
                lo = mid
            else:
                hi = mid - 1
        font.setPixelSize(lo)
        if len(self._font_cache) > 256:
            self._font_cache.clear()
        self._font_cache[key] = font
        return font
