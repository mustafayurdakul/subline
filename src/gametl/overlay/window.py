"""The overlay: a transparent, click-through, always-on-top window glued to
the game window, drawing translations at frame-pixel positions.

Coordinates: the app runs with Qt's high-DPI scaling disabled and the
process set to Per-Monitor-V2 DPI awareness, so widget coordinates are
physical pixels and capture-frame pixel (x, y) lands at overlay pixel (x, y).

Styles:
- "subtitle": one fixed font size and colour, centred in the selected zone,
  on a pill, with a soft shadow, or bare with an outline; a band covers the
  source line when the text is drawn elsewhere;
- "patch": the sampled background colour painted over the original and the
  translation drawn in the sampled text colour, in place;
- "pill": a dark rounded box with white outlined text, in place (for busy
  backgrounds);
- "outline": outlined text only, in place.

Line heights come from the font's own metrics (ascent plus descent), so
descenders are never clipped.
"""

from __future__ import annotations

import ctypes
import traceback
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass, field

from PySide6.QtCore import QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..capture.windows import foreground_window, is_minimized, is_window, window_rect
from ..geometry import RGB, Box
from ..layout.fit import TextLayout, fit_text
from ..layout.style import font_px_for

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

PILL_COLOR = QColor(0, 0, 0, 230)  # dark enough that the original text does not ghost through
OUTLINE_COLOR = QColor(0, 0, 0, 220)
DEBUG_COLOR = QColor(0, 255, 0)
WHITE = QColor(255, 255, 255)
_OUTLINE_OFFSETS = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
# A soft drop shadow, as games draw their own subtitles: a few offset copies
# of the text, the farther the fainter; (dx, dy) in pixels and the colour.
# (The settings window's preview mirrors these in SubtitlePreview.qml.)
_SHADOW_LAYERS = [
    ((1, 1), QColor(0, 0, 0, 170)),
    ((2, 2), QColor(0, 0, 0, 120)),
    ((3, 3), QColor(0, 0, 0, 70)),
    ((0, 2), QColor(0, 0, 0, 70)),
    ((2, 0), QColor(0, 0, 0, 70)),
]
_LAYOUT_CACHE_SIZE = 512
_REFERENCE_SIZES = (12, 16, 24, 32, 48, 100)  # font sizes the line-height ratio is measured at


@dataclass(slots=True)
class RenderBlock:
    """One thing to draw: a box in frame pixels with text lines."""

    bbox: Box
    lines: list[str] = field(default_factory=list)
    bg: RGB = (0, 0, 0)
    fg: RGB = (255, 255, 255)
    style: str = "patch"  # "patch" | "pill" | "outline" | "subtitle"
    source_lines: int = 1  # lines in the source text; sets the base font size unless font_px is given
    font_px: int | None = None  # base font size decided by the caller (style memory)
    prefer_grow: bool = True  # keep the font size and wrap into free space before shrinking
    room_below: int = 0  # free pixels the box may grow into
    room_above: int = 0
    outline: bool = False  # debug: draw the box outline only
    # subtitle style: text centred in `zone`; a band hides the source line when the text is drawn elsewhere
    zone: Box | None = None
    position: str = "bottom"  # "source" | "bottom" | "center"
    background: str = "pill"  # "pill" | "shadow" | "none"
    pill_alpha: int = 230
    bold: bool = False
    hide_source: bool = True  # cover the source line when the text is drawn elsewhere


@dataclass(slots=True)
class SubtitlePlacement:
    """Where a subtitle block lands: the laid-out text, its rectangle, the
    pill around it and the band over the source line."""

    layout: TextLayout
    text: QRect
    pill: QRect
    source: QRect


def subtitle_rect(zone: Box, anchor_y: int, text_w: int, text_h: int, position: str, margin: int = 12) -> QRect:
    """Where a subtitle of `text_w` x `text_h` goes inside `zone`: centred
    horizontally; vertically on the source line, at the bottom, or in the
    middle; always kept inside the zone."""
    zx0, zy0, zx1, zy1 = zone
    x = (zx0 + zx1) // 2 - text_w // 2
    if position == "bottom":
        y = zy1 - margin - text_h
    elif position == "center":
        y = (zy0 + zy1) // 2 - text_h // 2
    else:
        y = anchor_y - text_h // 2
    y = max(zy0 + margin, min(y, zy1 - margin - text_h))
    return QRect(x, y, text_w, text_h)


def source_font_px(box_height: int, source_lines: int) -> int:
    """Font size that matches the source text, from its line height."""
    return font_px_for(box_height / max(1, source_lines))


def _padded(box: Box, pad_x: int, pad_y: int) -> QRect:
    x0, y0, x1, y1 = box
    return QRect(x0 - pad_x, y0 - pad_y, (x1 - x0) + 2 * pad_x, (y1 - y0) + 2 * pad_y)


def _split_growth(extra: int, room_above: int, room_below: int) -> tuple[int, int]:
    """Split `extra` pixels of growth into (up, down), taking the side with
    more room first: subtitles near the bottom edge grow upward, a HUD line
    at the top grows downward."""
    if room_above > room_below:
        up = min(extra, room_above)
        return up, min(extra - up, room_below)
    down = min(extra, room_below)
    return min(extra - down, room_above), down


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
        self.paint_errors = 0

        self._blocks: list[RenderBlock] = []
        self._target_rect: Box | None = None
        self._fonts: dict[tuple[int, bool], tuple[QFont, QFontMetrics]] = {}  # by (pixel size, bold)
        self._spacing: dict[bool, float] = {}  # line height / font pixel size, per weight
        self._layouts: dict[tuple, TextLayout] = {}

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
        if self.exclude_from_capture:
            _user32.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE)

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
            self.paint_blocks(painter, self._blocks)
        except Exception:
            # A paint bug must never leave the painter open: Qt faults later if it does.
            self.paint_errors += 1
            if self.paint_errors <= 3:
                traceback.print_exc()
        finally:
            painter.end()

    # -- fonts and layout ----------------------------------------------------------

    def _font_and_metrics(self, px: int, bold: bool) -> tuple[QFont, QFontMetrics]:
        entry = self._fonts.get((px, bold))
        if entry is None:
            font = QFont(self.font_family)
            font.setPixelSize(px)
            font.setBold(bold)
            entry = self._fonts[(px, bold)] = (font, QFontMetrics(font))
        return entry

    def font_at(self, px: int, bold: bool = False) -> QFont:
        return self._font_and_metrics(px, bold)[0]

    def metrics_at(self, px: int, bold: bool = False) -> QFontMetrics:
        return self._font_and_metrics(px, bold)[1]

    def spacing_ratio(self, bold: bool = False) -> float:
        """Line height per pixel of font size, from the font's own metrics
        (ascent plus descent plus leading), so descenders fit the line. The
        largest ratio over common sizes: metrics round up at small sizes."""
        ratio = self._spacing.get(bold)
        if ratio is None:
            ratio = max(1.0, *(self.metrics_at(px, bold).height() / px for px in _REFERENCE_SIZES))
            self._spacing[bold] = ratio
        return ratio

    def measurer(self, bold: bool) -> Callable[[str, int], float]:
        return lambda text, px: float(self.metrics_at(px, bold).horizontalAdvance(text))

    def _cached_layout(self, key: tuple, build: Callable[[], TextLayout]) -> TextLayout:
        layout = self._layouts.get(key)
        if layout is None:
            if len(self._layouts) >= _LAYOUT_CACHE_SIZE:
                self._layouts.clear()
            layout = self._layouts[key] = build()
        return layout

    @staticmethod
    def _base_px(block: RenderBlock) -> int:
        """The font size to start from: the caller's, else the source text's."""
        return block.font_px or source_font_px(block.bbox[3] - block.bbox[1], block.source_lines)

    def _pads(self, bbox: Box) -> tuple[int, int]:
        """(horizontal, vertical) padding around a box: the sides get more on tall text."""
        return max(self.padding, int(0.2 * (bbox[3] - bbox[1]))), self.padding

    def layout_for(self, block: RenderBlock) -> TextLayout:
        """In-place layout: wrapped and sized for the block's box plus the
        free room around it."""
        x0, y0, x1, y1 = block.bbox
        width, height = x1 - x0, y1 - y0
        base_px = self._base_px(block)
        room = block.room_below + block.room_above  # only the sum matters to the layout
        ratio = self.spacing_ratio(block.bold)
        key = ("inplace", tuple(block.lines), width, height, base_px, block.prefer_grow, room, block.bold)
        return self._cached_layout(
            key,
            lambda: fit_text(
                "\n".join(block.lines),
                width,
                height,
                self.measurer(block.bold),
                base_px,
                max_height=height + room,
                line_spacing=ratio,
                prefer_grow=block.prefer_grow,
            ),
        )

    def place_subtitle(self, block: RenderBlock) -> SubtitlePlacement:
        """Lay a subtitle block out at its fixed size, wrapping within the
        zone when it is long, and work out the text, pill and source
        rectangles."""
        assert block.zone is not None
        _x0, y0, _x1, y1 = block.bbox
        zx0, zy0, zx1, zy1 = block.zone
        source = _padded(block.bbox, *self._pads(block.bbox))
        font_px = self._base_px(block)
        ratio = self.spacing_ratio(block.bold)
        margin = max(12, font_px // 2)
        width = max(50, (zx1 - zx0) - 2 * margin)
        key = ("subtitle", tuple(block.lines), width, font_px, zy1 - zy0, block.bold)
        layout = self._cached_layout(
            key,
            lambda: fit_text(
                "\n".join(block.lines),
                width,
                int(font_px * ratio) + 1,
                self.measurer(block.bold),
                font_px,
                max_height=(zy1 - zy0) - 2 * margin,
                line_spacing=ratio,
                prefer_grow=True,
            ),
        )
        # metrics_at registers the font even when the wrapper never measured (a one-word line).
        metrics = self.metrics_at(layout.font_px, block.bold)
        text_w = min(width, max(metrics.horizontalAdvance(line) for line in layout.lines))
        text = subtitle_rect(block.zone, (y0 + y1) // 2, text_w, layout.height, block.position, margin)
        # The pill clears the descenders below and the ascenders above by the font's own measure.
        pill = text.adjusted(
            -font_px // 2, -max(2, metrics.descent() // 2), font_px // 2, max(2, metrics.descent() // 2)
        )
        return SubtitlePlacement(layout, text, pill, source)

    # -- painting ----------------------------------------------------------------

    def paint_blocks(self, p: QPainter, blocks: list[RenderBlock]) -> None:
        """Draw blocks with `p`, which may target this window or any image."""
        for block in blocks:
            self._paint_block(p, block)

    def _paint_block(self, p: QPainter, block: RenderBlock) -> None:
        if block.outline:
            p.setPen(QPen(DEBUG_COLOR, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(_padded(block.bbox, *self._pads(block.bbox)))
        elif not block.lines:
            return
        elif block.style == "subtitle" and block.zone is not None:
            self._paint_subtitle(p, block)
        else:
            self._paint_in_place(p, block)

    def _paint_in_place(self, p: QPainter, block: RenderBlock) -> None:
        """Patch, pill or outline style on the block's own box, grown into
        the free room when the translation needs more lines."""
        layout = self.layout_for(block)
        x0, y0, x1, y1 = block.bbox
        # Extra lines push the box up or down into the free room reported by the pipeline.
        up, down = _split_growth(max(0, layout.height - (y1 - y0)), block.room_above, block.room_below)
        top, bottom = y0 - up, y1 + down
        rect = _padded((x0, top, x1, bottom), *self._pads(block.bbox))

        if block.style == "patch":
            p.fillRect(rect, QColor(*block.bg))
            fg, decoration = QColor(*block.fg), "none"
        elif block.style == "pill":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(PILL_COLOR)
            p.drawRoundedRect(rect, 6, 6)
            fg, decoration = WHITE, "outline"
        else:  # outline
            fg = QColor(*block.fg) if block.fg != block.bg else WHITE
            decoration = "outline"

        p.setFont(self.font_at(layout.font_px, block.bold))
        total = len(layout.lines) * layout.line_height
        text_top = top + max(0.0, ((bottom - top) - total) / 2)
        area = QRect(x0, int(text_top), x1 - x0, int(total) + 1)
        self._draw_lines(p, layout.lines, area, layout.line_height, Qt.AlignmentFlag.AlignCenter, fg, decoration)

    def _paint_subtitle(self, p: QPainter, block: RenderBlock) -> None:
        """One fixed style, centred in the zone. Background "pill": a
        rounded box, merged with the band over the source line when they
        overlap; "shadow": the text with a soft drop shadow, no box; "none":
        outlined text. The band hides the source line when the text is
        drawn elsewhere (if `hide_source`)."""
        placed = self.place_subtitle(block)
        p.setPen(Qt.PenStyle.NoPen)
        pill_color = QColor(0, 0, 0, max(0, min(255, block.pill_alpha)))
        if block.background == "pill" and placed.pill.intersects(placed.source):
            p.setBrush(pill_color)
            p.drawRoundedRect(placed.pill.united(placed.source), 8, 8)
        else:
            if block.hide_source:
                p.setBrush(PILL_COLOR)  # the band must hide the original whatever the pill's opacity
                p.drawRoundedRect(placed.source, 6, 6)
            if block.background == "pill":
                p.setBrush(pill_color)
                p.drawRoundedRect(placed.pill, 8, 8)
        p.setFont(self.font_at(placed.layout.font_px, block.bold))
        decoration = "shadow" if block.background == "shadow" else "outline"
        self._draw_lines(
            p,
            placed.layout.lines,
            placed.text,
            placed.layout.line_height,
            Qt.AlignmentFlag.AlignCenter,
            QColor(*block.fg),
            decoration,
        )

    @staticmethod
    def _draw_lines(
        p: QPainter,
        lines: list[str],
        area: QRect,
        line_h: float,
        flags: Qt.AlignmentFlag,
        fg: QColor,
        decoration: str,
    ) -> None:
        """Draw `lines` top to bottom, each in a row `line_h` tall, with an
        outline, a drop shadow or nothing behind the text."""
        top = float(area.top())
        for line in lines:
            rect = QRect(area.left(), int(top), area.width(), int(line_h) + 1)
            if decoration == "outline":
                p.setPen(OUTLINE_COLOR)
                for dx, dy in _OUTLINE_OFFSETS:
                    p.drawText(rect.translated(dx, dy), flags, line)
            elif decoration == "shadow":
                for (dx, dy), color in _SHADOW_LAYERS:
                    p.setPen(color)
                    p.drawText(rect.translated(dx, dy), flags, line)
            p.setPen(fg)
            p.drawText(rect, flags, line)
            top += line_h
