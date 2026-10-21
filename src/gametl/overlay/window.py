"""The overlay: a transparent, click-through, always-on-top window glued to
the game window, drawing translated blocks at frame-pixel positions.

Coordinates: the app runs with Qt's high-DPI scaling disabled and the process
set to Per-Monitor-V2 DPI awareness, so widget coordinates are physical
pixels and a capture-frame pixel (x, y) lands at overlay pixel (x, y).

Styles: "patch" paints the sampled background colour over the original and
draws the translation in the sampled text colour; "pill" draws a translucent
dark rounded box with white outlined text (for busy backgrounds); "outline"
draws outlined text only.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

from PySide6.QtCore import QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..capture.windows import foreground_window, is_minimized, is_window, window_rect
from ..layout.fit import TextLayout, fit_text

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

_OUTLINE_OFFSETS = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


@dataclass(slots=True)
class RenderBlock:
    """One thing to draw: a box in frame pixels with text lines."""

    bbox: Box
    lines: list[str] = field(default_factory=list)
    bg: RGB = (0, 0, 0)
    fg: RGB = (255, 255, 255)
    align: str = "center"  # "center" | "left"
    style: str = "patch"  # "patch" | "pill" | "outline"
    source_lines: int = 1  # lines in the source text; sets the base font size
    room_below: int = 0  # free pixels the box may grow into
    room_above: int = 0
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
        self._fonts: dict[int, QFont] = {}
        self._metrics: dict[int, QFontMetrics] = {}
        self._layout_cache: dict[tuple, TextLayout] = {}

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

    # -- text fitting ------------------------------------------------------------

    def font_at(self, px: int) -> QFont:
        font = self._fonts.get(px)
        if font is None:
            font = QFont(self.font_family)
            font.setPixelSize(px)
            self._fonts[px] = font
            self._metrics[px] = QFontMetrics(font)
        return font

    def measure(self, text: str, px: int) -> float:
        self.font_at(px)
        return float(self._metrics[px].horizontalAdvance(text))

    def layout_for(self, block: RenderBlock) -> TextLayout:
        x0, y0, x1, y1 = block.bbox
        width, height = x1 - x0, y1 - y0
        key = (tuple(block.lines), width, height, block.source_lines, block.room_below, block.room_above)
        cached = self._layout_cache.get(key)
        if cached is not None:
            return cached
        base_px = max(6, int(height / max(1, block.source_lines) * 0.8))
        layout = fit_text(
            "\n".join(block.lines),
            width,
            height,
            self.measure,
            base_px,
            max_height=height + block.room_below + block.room_above,
        )
        if len(self._layout_cache) > 512:
            self._layout_cache.clear()
        self._layout_cache[key] = layout
        return layout

    def fit_font(self, lines: list[str], width: int, height: int) -> QFont:
        """Font for `lines` in a box, no wrapping or growth (kept for tests
        and single-line callers)."""
        layout = fit_text("\n".join(lines), width, height, self.measure, max(6, int(height / max(1, len(lines)) * 0.8)))
        return self.font_at(layout.font_px)

    # -- painting ----------------------------------------------------------------

    def _paint_block(self, p: QPainter, block: RenderBlock) -> None:
        x0, y0, x1, y1 = block.bbox
        pad = self.padding
        pad_x = max(pad, int(0.2 * (y1 - y0)))
        if block.outline:
            p.setPen(QPen(QColor(0, 255, 0), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRect(x0 - pad_x, y0 - pad, (x1 - x0) + 2 * pad_x, (y1 - y0) + 2 * pad))
            return
        if not block.lines:
            return

        layout = self.layout_for(block)
        height = y1 - y0
        extra = max(0, layout.height - height)
        # Grow toward the side with more room first: subtitles near the bottom
        # edge grow upward, a HUD line at the top grows downward.
        if block.room_above > block.room_below:
            up = min(extra, block.room_above)
            down = min(extra - up, block.room_below)
        else:
            down = min(extra, block.room_below)
            up = min(extra - down, block.room_above)
        ry0, ry1 = y0 - up, y1 + down
        rect = QRect(x0 - pad_x, ry0 - pad, (x1 - x0) + 2 * pad_x, (ry1 - ry0) + 2 * pad)

        if block.style == "patch":
            p.fillRect(rect, QColor(*block.bg))
            fg = QColor(*block.fg)
            outlined = False
        elif block.style == "pill":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 215))  # opaque enough that the original does not ghost through
            p.drawRoundedRect(rect, 6, 6)
            fg = QColor(255, 255, 255)
            outlined = True
        else:  # outline
            fg = QColor(*block.fg) if block.fg != block.bg else QColor(255, 255, 255)
            outlined = True

        p.setFont(self.font_at(layout.font_px))
        h_align = Qt.AlignmentFlag.AlignHCenter if block.align == "center" else Qt.AlignmentFlag.AlignLeft
        flags = Qt.AlignmentFlag.AlignVCenter | h_align
        total = len(layout.lines) * layout.line_height
        ty = ry0 + max(0.0, ((ry1 - ry0) - total) / 2)
        for line in layout.lines:
            r = QRect(x0, int(ty), x1 - x0, int(layout.line_height) + 1)
            if outlined:
                p.setPen(QColor(0, 0, 0, 220))
                for dx, dy in _OUTLINE_OFFSETS:
                    p.drawText(r.translated(dx, dy), flags, line)
            p.setPen(fg)
            p.drawText(r, flags, line)
            ty += layout.line_height
