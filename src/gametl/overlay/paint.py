"""How translations are drawn: fonts, layouts and the painting of render
blocks. The overlay window, the settings window's preview and the demo
renderer all paint through one BlockPainter, so they look the same.

Styles:
- "subtitle": one fixed font size and colour, centred in the selected zone,
  on a pill (plain text), with a soft shadow, or bare with an outline; with
  hide_source a band covers the source line, merged into the pill when they
  overlap; blocks shown at once at "bottom" or "center" are stacked, and
  no band covers another block's text;
- "patch": the sampled background colour painted over the original and the
  translation drawn in the sampled text colour, in place;
- "pill": a dark rounded box with white text, in place (for busy
  backgrounds);
- "outline": outlined text only, in place.

Line heights come from the font's own metrics (ascent plus descent), so
descenders are never clipped.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen

from ..geometry import RGB, Box
from ..layout.fit import TextLayout, fit_text

WEIGHTS = {
    "regular": QFont.Weight.Normal,
    "medium": QFont.Weight.Medium,
    "semibold": QFont.Weight.DemiBold,
    "bold": QFont.Weight.Bold,
}
PILL_COLOR = QColor(0, 0, 0, 230)  # dark enough that the original text does not ghost through
OUTLINE_COLOR = QColor(0, 0, 0, 220)
DEBUG_COLOR = QColor(0, 255, 0)
WHITE = QColor(255, 255, 255)
_OUTLINE_OFFSETS = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
# A soft drop shadow, as games draw their own subtitles: a few offset copies
# of the text, the farther the fainter; (dx, dy) in pixels and the colour.
_SHADOW_LAYERS = [
    ((1, 1), QColor(0, 0, 0, 170)),
    ((2, 2), QColor(0, 0, 0, 120)),
    ((3, 3), QColor(0, 0, 0, 70)),
    ((0, 2), QColor(0, 0, 0, 70)),
    ((2, 0), QColor(0, 0, 0, 70)),
]
_CACHE_SIZE = 512  # layouts
_REFERENCE_SIZES = (12, 16, 24, 32, 48, 100)  # font sizes the line-height ratio is measured at
# Subtitle positions that ignore the source line, so blocks shown at once would share one spot: they are stacked.
_STACKED = ("bottom", "center")
_STACK_GAP = 4  # pixels between the pills of stacked subtitles
_PADDING = 3  # pixels round a box: the least the in-place background reaches past the text


@dataclass(slots=True)
class RenderBlock:
    """One thing to draw: a box in frame pixels with text lines."""

    bbox: Box
    lines: list[str] = field(default_factory=list)
    bg: RGB = (0, 0, 0)  # the sampled background, for the in-place patch and outline styles
    fg: RGB = (255, 255, 255)
    style: str = "patch"  # "patch" | "pill" | "outline" | "subtitle"
    font_px: int = 0  # base font size from the producer (style memory, zone style or settings); unused by debug boxes
    room_below: int = 0  # free pixels the box may grow into
    room_above: int = 0
    debug_box: bool = False  # debug: draw the box's outline only, no text
    # subtitle style: text centred in `zone`; with hide_source a band covers the source line
    zone: Box | None = None
    position: str = "bottom"  # "source" | "bottom" | "center"
    background: str = "pill"  # "pill" | "shadow" | "none"
    pill_alpha: int = 230
    weight: str = "regular"  # a key of WEIGHTS
    anchor_y: int | None = None  # subtitle at "source": the line's centre to hold; None = the box's own
    hide_source: bool = True  # cover the source line with a band, merged into the pill when they overlap


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
    middle; kept inside the zone when it fits, else top-aligned at the margin."""
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


def _is_subtitle(block: RenderBlock) -> bool:
    """A block drawn in the subtitle style, placed in its zone."""
    return not block.debug_box and bool(block.lines) and block.style == "subtitle" and block.zone is not None


def _shift(placed: SubtitlePlacement, dy: int) -> None:
    """Move a subtitle's text and pill by `dy`; the band stays on the source line."""
    placed.text = placed.text.translated(0, dy)
    placed.pill = placed.pill.translated(0, dy)


def _stack(stack: list[SubtitlePlacement], zone: Box, position: str) -> None:
    """Move the placements in `stack`, top to bottom in source order, so no
    two pills meet: from the lowest, which stays put, each one above ends
    `_STACK_GAP` over the next one's pill. At "center" the whole stack is
    then centred in the zone. A stack that fits the zone stays inside it; a
    taller one rises above it, but never past the top of the window. At
    "bottom" the lowest line keeps its place; at "center" the stack's foot
    stays inside the zone (centring a tall stack would push its lower lines
    below the zone, and past the window's bottom when the zone reaches it)."""
    for upper, lower in reversed(list(pairwise(stack))):
        _shift(upper, lower.pill.top() - _STACK_GAP - (upper.pill.top() + upper.pill.height()))
    dy = 0
    if position == "center":
        top, end = stack[0].pill.top(), stack[-1].pill.top() + stack[-1].pill.height()
        dy = (zone[1] + zone[3]) // 2 - (top + end) // 2
        dy = min(dy, zone[3] - end)
    dy = max(dy, -stack[0].pill.top())  # frame pixel 0 is the window's top edge
    for placed in stack:
        _shift(placed, dy)


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


class BlockPainter:
    """Lays out and paints render blocks with one font family, caching
    fonts, metrics and layouts."""

    def __init__(self, font_family: str = "Segoe UI") -> None:
        self.font_family = font_family
        self._fonts: dict[tuple[int, str], tuple[QFont, QFontMetrics]] = {}  # by (pixel size, weight)
        self._spacing: dict[str, float] = {}  # line height / font pixel size, per weight
        self._layouts: dict[tuple, TextLayout] = {}

    def set_font(self, family: str) -> bool:
        """Use `family` from now on; True when that is a change (the caches go)."""
        if family == self.font_family:
            return False
        self.font_family = family
        self._fonts.clear()
        self._spacing.clear()
        self._layouts.clear()
        return True

    # -- fonts and layout ----------------------------------------------------------

    def _font_and_metrics(self, px: int, weight: str) -> tuple[QFont, QFontMetrics]:
        entry = self._fonts.get((px, weight))
        if entry is None:
            font = QFont(self.font_family)
            font.setPixelSize(px)
            font.setWeight(WEIGHTS.get(weight, QFont.Weight.Normal))
            entry = self._fonts[(px, weight)] = (font, QFontMetrics(font))
        return entry

    def font_at(self, px: int, weight: str = "regular") -> QFont:
        return self._font_and_metrics(px, weight)[0]

    def metrics_at(self, px: int, weight: str = "regular") -> QFontMetrics:
        return self._font_and_metrics(px, weight)[1]

    def spacing_ratio(self, weight: str = "regular") -> float:
        """Line height per pixel of font size, from the font's own metrics
        (ascent plus descent), so descenders fit the line. The largest ratio
        over common sizes: metrics round up at small sizes."""
        ratio = self._spacing.get(weight)
        if ratio is None:
            ratio = max(1.0, *(self.metrics_at(px, weight).height() / px for px in _REFERENCE_SIZES))
            self._spacing[weight] = ratio
        return ratio

    def measurer(self, weight: str = "regular") -> Callable[[str, int], float]:
        return lambda text, px: float(self.metrics_at(px, weight).horizontalAdvance(text))

    def _layout(self, key: tuple, build: Callable[[], TextLayout]) -> TextLayout:
        """The layout cached under `key`, built on first use."""
        layout = self._layouts.get(key)
        if layout is None:
            if len(self._layouts) >= _CACHE_SIZE:
                self._layouts.clear()
            layout = self._layouts[key] = build()
        return layout

    def _pads(self, bbox: Box) -> tuple[int, int]:
        """(horizontal, vertical) padding around a box: the sides get more on tall text."""
        return max(_PADDING, int(0.2 * (bbox[3] - bbox[1]))), _PADDING

    def layout_for(self, block: RenderBlock) -> TextLayout:
        """In-place layout: wrapped and sized for the block's box plus the
        free room around it."""
        x0, y0, x1, y1 = block.bbox
        width, height = x1 - x0, y1 - y0
        base_px = block.font_px
        room = block.room_below + block.room_above  # only the sum matters to the layout
        ratio = self.spacing_ratio(block.weight)
        key = ("inplace", tuple(block.lines), width, height, base_px, room, block.weight)
        return self._layout(
            key,
            lambda: fit_text(
                "\n".join(block.lines),
                width,
                height,
                self.measurer(block.weight),
                base_px,
                max_height=height + room,
                line_spacing=ratio,
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
        font_px = block.font_px
        ratio = self.spacing_ratio(block.weight)
        margin = max(12, font_px // 2)
        width = max(50, (zx1 - zx0) - 2 * margin)
        key = ("subtitle", tuple(block.lines), width, font_px, zy1 - zy0, block.weight)
        layout = self._layout(
            key,
            lambda: fit_text(
                "\n".join(block.lines),
                width,
                int(font_px * ratio) + 1,
                self.measurer(block.weight),
                font_px,
                max_height=(zy1 - zy0) - 2 * margin,
                line_spacing=ratio,
            ),
        )
        # Metrics of the size the layout settled on.
        metrics = self.metrics_at(layout.font_px, block.weight)
        text_w = min(width, max(metrics.horizontalAdvance(line) for line in layout.lines))
        anchor = block.anchor_y if block.anchor_y is not None else (y0 + y1) // 2
        text = subtitle_rect(block.zone, anchor, text_w, layout.height, block.position, margin)
        # The pill clears the descenders below and the ascenders above by the font's own measure.
        side, edge = layout.font_px // 2, max(2, metrics.descent() // 2)
        pill = text.adjusted(-side, -edge, side, edge)
        return SubtitlePlacement(layout, text, pill, source)

    def place_subtitles(self, blocks: list[RenderBlock]) -> dict[int, SubtitlePlacement]:
        """Placements of the subtitle blocks among `blocks`, by index.

        At "bottom" and "center" every block lands at the same height, so the
        blocks sharing a zone and position are stacked in the order of their
        source lines (see _stack): one translation never covers another."""
        placements = {i: self.place_subtitle(block) for i, block in enumerate(blocks) if _is_subtitle(block)}
        stacks: dict[tuple, list[int]] = {}  # by (zone, position)
        for i in placements:
            if blocks[i].position in _STACKED:
                stacks.setdefault((blocks[i].zone, blocks[i].position), []).append(i)
        for (zone, position), members in stacks.items():
            if len(members) > 1:
                members.sort(key=lambda i: (blocks[i].bbox[1], blocks[i].bbox[0]))
                _stack([placements[i] for i in members], zone, position)
        return placements

    # -- painting ----------------------------------------------------------------

    def paint_blocks(self, p: QPainter, blocks: list[RenderBlock]) -> None:
        """Draw blocks with `p`, which may target a window or any image, in
        list order. The texts of the subtitles go on after every background,
        so a band over one block's source line never covers another block's
        translation, whatever the order of the list. (Something meant to lie
        under a band, as the settings preview's game line, is drawn by a
        call of its own before.)"""
        placements = self.place_subtitles(blocks)
        for i, block in enumerate(blocks):
            placed = placements.get(i)
            if placed is None:
                self._paint_block(p, block)
            else:
                self._paint_subtitle_background(p, block, placed)
        for i, placed in placements.items():
            self._paint_subtitle_text(p, blocks[i], placed)

    def _paint_block(self, p: QPainter, block: RenderBlock) -> None:
        """A debug box, or a block drawn on its own box."""
        if block.debug_box:
            p.setPen(QPen(DEBUG_COLOR, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(_padded(block.bbox, *self._pads(block.bbox)))
        elif block.lines:
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
            fg, decoration = WHITE, "none"  # the box is the contrast, as on the subtitle pill
        else:  # outline
            fg = QColor(*block.fg) if block.fg != block.bg else WHITE
            decoration = "outline"

        total = len(layout.lines) * layout.line_height
        text_top = top + max(0.0, ((bottom - top) - total) / 2)
        area = QRect(x0, int(text_top), x1 - x0, int(total) + 1)
        font = self.font_at(layout.font_px, block.weight)
        self._draw_lines(p, layout.lines, area, layout.line_height, fg, decoration, font)

    def _paint_subtitle_background(self, p: QPainter, block: RenderBlock, placed: SubtitlePlacement) -> None:
        """Background "pill": a rounded box sized by the text; "shadow" and
        "none" draw no box. With `hide_source` a band covers the source line,
        merged into the pill when they overlap."""
        p.setPen(Qt.PenStyle.NoPen)
        # The one clamp every producer passes through; int() takes a float from a hand-edited profile.
        pill_color = QColor(0, 0, 0, max(0, min(255, int(block.pill_alpha))))
        if block.background == "pill" and block.hide_source and placed.pill.intersects(placed.source):
            # One rounded box round both, in two parts: the part over the source line dark enough
            # to hide the original, however light the pill; the rest at the pill's own opacity.
            shape = QPainterPath()
            shape.addRoundedRect(QRectF(placed.pill.united(placed.source)), 8, 8)
            band = QPainterPath()
            band.addRect(QRectF(placed.source))
            band = band.intersected(shape)
            p.setBrush(QColor(0, 0, 0, max(pill_color.alpha(), PILL_COLOR.alpha())))
            p.drawPath(band)
            p.setBrush(pill_color)
            p.drawPath(shape.subtracted(band))
        else:
            if block.hide_source:
                p.setBrush(PILL_COLOR)  # the band must hide the original whatever the pill's opacity
                p.drawRoundedRect(placed.source, 6, 6)
            if block.background == "pill":
                p.setBrush(pill_color)
                p.drawRoundedRect(placed.pill, 8, 8)

    def _paint_subtitle_text(self, p: QPainter, block: RenderBlock, placed: SubtitlePlacement) -> None:
        """The subtitle's lines: with a soft drop shadow ("shadow"), outlined
        ("none") or plain on the pill."""
        if block.background == "shadow":
            decoration = "shadow"
        elif block.background == "none":
            decoration = "outline"  # bare text needs an edge to read over anything
        else:
            decoration = "none"  # the pill is the contrast; an outline would only thicken the letters
        layout = placed.layout
        font = self.font_at(layout.font_px, block.weight)
        self._draw_lines(p, layout.lines, placed.text, layout.line_height, QColor(*block.fg), decoration, font)

    def _draw_lines(
        self,
        p: QPainter,
        lines: list[str],
        area: QRect,
        line_h: float,
        fg: QColor,
        decoration: str,
        font: QFont,
    ) -> None:
        """Draw `lines` in `font` top to bottom, each centred in a row
        `line_h` tall, with an outline, a drop shadow or nothing behind the
        text."""
        p.setFont(font)
        flags = Qt.AlignmentFlag.AlignCenter
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
