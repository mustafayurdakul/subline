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
    style: str = "patch"  # "patch" | "pill" | "outline" | "subtitle"
    source_lines: int = 1  # lines in the source text; sets the base font size unless font_px is given
    font_px: int | None = None  # base font size decided by the caller (style memory)
    prefer_grow: bool = True  # keep the font size and wrap into free space before shrinking
    room_below: int = 0  # free pixels the box may grow into
    room_above: int = 0
    outline: bool = False  # debug: draw the box outline only
    # subtitle style: draw the text centred in `zone` on a pill; the pill (or a
    # matching band) hides the source line
    zone: Box | None = None
    position: str = "source"  # "source" | "bottom" | "center"
    pill: bool = True
    hide_source: bool = True  # cover the source line when the text is drawn elsewhere


def subtitle_rect(zone: Box, anchor_y: int, text_w: int, text_h: int, position: str, margin: int = 12) -> QRect:
    """Where a subtitle of `text_w` x `text_h` goes inside `zone`: centred
    horizontally; vertically on the source line, at the bottom, or in the
    middle, always kept inside the zone."""
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
        try:
            for block in self._blocks:
                self._paint_block(painter, block)
        except Exception:  # a paint bug must never leave the painter open: Qt then faults later
            import traceback

            self._paint_errors = getattr(self, "_paint_errors", 0) + 1
            if self._paint_errors <= 3:
                traceback.print_exc()
        finally:
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
        key = (
            tuple(block.lines), width, height, block.source_lines, block.font_px,
            block.prefer_grow, block.room_below, block.room_above,
        )
        cached = self._layout_cache.get(key)
        if cached is not None:
            return cached
        base_px = block.font_px or max(6, int(height / max(1, block.source_lines) * 0.8))
        layout = fit_text(
            "\n".join(block.lines),
            width,
            height,
            self.measure,
            base_px,
            max_height=height + block.room_below + block.room_above,
            prefer_grow=block.prefer_grow,
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
        if block.style == "subtitle" and block.zone is not None:
            self._paint_subtitle(p, block, pad, pad_x)
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
        self._draw_lines(p, layout.lines, QRect(x0, int(ty), x1 - x0, int(total) + 1), layout.line_height, flags, fg, outlined)

    def _draw_lines(self, p: QPainter, lines: list[str], area: QRect, line_h: float, flags, fg: QColor, outlined: bool) -> None:
        ty = float(area.top())
        for line in lines:
            r = QRect(area.left(), int(ty), area.width(), int(line_h) + 1)
            if outlined:
                p.setPen(QColor(0, 0, 0, 220))
                for dx, dy in _OUTLINE_OFFSETS:
                    p.drawText(r.translated(dx, dy), flags, line)
            p.setPen(fg)
            p.drawText(r, flags, line)
            ty += line_h

    def _paint_subtitle(self, p: QPainter, block: RenderBlock, pad: int, pad_x: int) -> None:
        """Subtitle mode: the translation in one fixed style, centred in the
        zone, on a near-opaque pill. The pill is widened to cover the source
        line when the two overlap; when the text is placed elsewhere, a
        matching band hides the source line (if `hide_source`)."""
        x0, y0, x1, y1 = block.bbox
        zx0, zy0, zx1, zy1 = block.zone  # type: ignore[misc]
        source = QRect(x0 - pad_x, y0 - pad, (x1 - x0) + 2 * pad_x, (y1 - y0) + 2 * pad)

        font_px = block.font_px or max(6, int((y1 - y0) / max(1, block.source_lines) * 0.8))
        margin = max(12, font_px // 2)
        width = max(50, (zx1 - zx0) - 2 * margin)
        key = ("subtitle", tuple(block.lines), width, font_px, zy1 - zy0)
        layout = self._layout_cache.get(key)
        if layout is None:
            layout = fit_text(
                "\n".join(block.lines), width, int(font_px * 1.15), self.measure, font_px,
                max_height=(zy1 - zy0) - 2 * margin, prefer_grow=True,
            )
            if len(self._layout_cache) > 512:
                self._layout_cache.clear()
            self._layout_cache[key] = layout
        font = self.font_at(layout.font_px)  # registers the metrics too (a one-word line never measured)
        metrics = self._metrics[layout.font_px]
        text_w = min(width, max(metrics.horizontalAdvance(ln) for ln in layout.lines))
        rect = subtitle_rect(block.zone, (y0 + y1) // 2, text_w, layout.height, block.position, margin)  # type: ignore[arg-type]
        pill_rect = rect.adjusted(-font_px // 2, -font_px // 5, font_px // 2, font_px // 5)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 230))
        if block.pill and pill_rect.intersects(source):
            p.drawRoundedRect(pill_rect.united(source), 8, 8)  # one shape covers both
        else:
            if block.hide_source:
                p.drawRoundedRect(source, 6, 6)
            if block.pill:
                p.drawRoundedRect(pill_rect, 8, 8)
        p.setFont(font)
        flags = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        self._draw_lines(p, layout.lines, rect, layout.line_height, flags, QColor(*block.fg), outlined=True)
