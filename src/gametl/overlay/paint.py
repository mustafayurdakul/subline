"""How translations are drawn: fonts, layouts and the painting of render
blocks and the chat card. The overlay window, the settings window's
preview and the demo renderer all paint through one BlockPainter, so they
look the same.

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

The chat card (ChatCard) is the transcript of chat mode: the last lines of
dialogue on a translucent card in a corner, each with a bar in its
speaker's colour, the name over the words and the time it was said at the
right.

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
from ..layout.fit import TextLayout, fit_text, wrap_words

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
# The chat card. Speakers take the palette's colours in the order they first speak: light,
# distinct and readable on the dark card. Sizes are in the card's font size, so the card
# scales with the game's subtitles.
CHAT_PALETTE: tuple[RGB, ...] = (
    (242, 193, 78),  # amber
    (127, 184, 255),  # sky
    (142, 224, 170),  # mint
    (255, 150, 170),  # rose
    (190, 170, 255),  # lavender
    (255, 178, 120),  # peach
)
CHAT_CARD_RGB = (12, 12, 16)
CHAT_BORDER_ALPHA = 28  # of a white hairline that lifts the card off a dark scene, at full card opacity
CHAT_CORNERS = ("bottom-left", "bottom-right", "top-left", "top-right")
CHAT_NAME_SCALE = 0.85  # the name's font size, of the card's: a heading over the words
CHAT_STAMP_SCALE = 0.55  # the time's font size, of the card's
CHAT_STAMP_ALPHA = 100  # the time a line was said: small and faint at the right of the name row
CHAT_BAR_SCALE = 0.15  # the width of the bar in the speaker's colour beside each line, of the font size
CHAT_BAR_PLAIN = QColor(255, 255, 255, 90)  # the bar of a line with no speaker
_CHAT_SHADOW_BELOW = 128  # a card fainter than this no longer carries its text: the text gets a shadow


@dataclass(slots=True)
class RenderBlock:
    """One thing to draw: a box in frame pixels with text lines."""

    bbox: Box
    lines: list[str] = field(default_factory=list)
    bg: RGB = (0, 0, 0)
    fg: RGB = (255, 255, 255)
    style: str = "patch"  # "patch" | "pill" | "outline" | "subtitle"
    font_px: int = 0  # base font size, set by every producer of text (style memory); unused by debug outlines
    room_below: int = 0  # free pixels the box may grow into
    room_above: int = 0
    outline: bool = False  # debug: draw the box outline only
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


@dataclass(slots=True)
class ChatLine:
    """One utterance on the chat card."""

    speaker: str  # "" when no speaker was named
    text: str
    speaker_index: int = -1  # picks the name's colour from CHAT_PALETTE; -1 = no speaker
    stamp: str = ""  # when it was said, "HH:MM:SS"; "" shows none


@dataclass(slots=True)
class ChatCard:
    """The chat transcript to draw: `lines`, oldest first, on a card `width`
    of `area`'s width in `corner`; at a bottom corner the card sits above
    `zone` (the area read, where the game's own subtitles are), so the two
    never overlap. `covers` are source lines to hide under a band."""

    area: Box
    lines: list[ChatLine] = field(default_factory=list)
    zone: Box | None = None
    corner: str = "bottom-left"  # one of CHAT_CORNERS
    width: float = 0.38
    font_px: int = 32
    fg: RGB = (255, 255, 255)
    weight: str = "semibold"
    alpha: int = 230  # of the card
    covers: list[Box] = field(default_factory=list)


Drawable = RenderBlock | ChatCard


@dataclass(slots=True)
class ChatEntry:
    """One line of the card as laid out: the bar beside it, the name's row
    (empty without a speaker), the stamp at the right of that row (or of
    the first words row) and the words' rectangle with the rows they wrap
    to."""

    line: ChatLine
    bar: QRect
    stamp: QRect
    name: QRect
    text: QRect
    rows: list[str]


@dataclass(slots=True)
class ChatPlacement:
    card: QRect
    entries: list[ChatEntry]
    line_height: float
    radius: int


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


def _is_subtitle(block: RenderBlock) -> bool:
    """A block drawn in the subtitle style, placed in its zone."""
    return not block.outline and bool(block.lines) and block.style == "subtitle" and block.zone is not None


def name_px(font_px: int) -> int:
    """The speaker name's font size for a card of `font_px`."""
    return max(6, round(font_px * CHAT_NAME_SCALE))


def stamp_px(font_px: int) -> int:
    """The time stamp's font size for a card of `font_px`."""
    return max(6, round(font_px * CHAT_STAMP_SCALE))


def chat_room(card: ChatCard, margin: int) -> tuple[int, int]:
    """The top and bottom edges a card may span: `margin` in from the area's
    edges, and above the zone when it lies in the lower half of the area
    (the subtitle strip), so the card never covers the game's own lines."""
    _, ay0, _, ay1 = card.area
    bottom = ay1 - margin
    if card.zone is not None and card.zone[1] > (ay0 + ay1) / 2:
        bottom = card.zone[1] - margin // 2
    return ay0 + margin, bottom


def chat_card_rect(card: ChatCard, width: int, height: int, margin: int) -> QRect:
    """Where a card `width` x `height` goes: in its corner of the room (see
    chat_room). A card taller than the room keeps its top edge in view."""
    ax0, _, ax1, _ = card.area
    top, bottom = chat_room(card, margin)
    x = ax0 + margin if card.corner.endswith("left") else ax1 - margin - width
    y = top if card.corner.startswith("top") else max(top, bottom - height)
    return QRect(x, y, width, height)


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

    def __init__(self, font_family: str = "Segoe UI", padding: int = 3) -> None:
        self.font_family = font_family
        self.padding = padding
        self._fonts: dict[tuple[int, str], tuple[QFont, QFontMetrics]] = {}  # by (pixel size, weight)
        self._spacing: dict[str, float] = {}  # line height / font pixel size, per weight
        self._layouts: dict[tuple, TextLayout] = {}

    def set_font(self, family: str) -> None:
        if family != self.font_family:
            self.font_family = family
            self._fonts.clear()
            self._spacing.clear()
            self._layouts.clear()

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

    @staticmethod
    def _cached(cache: dict, key: tuple, build: Callable[[], object]):
        value = cache.get(key)
        if value is None:
            if len(cache) >= _CACHE_SIZE:
                cache.clear()
            value = cache[key] = build()
        return value

    def _pads(self, bbox: Box) -> tuple[int, int]:
        """(horizontal, vertical) padding around a box: the sides get more on tall text."""
        return max(self.padding, int(0.2 * (bbox[3] - bbox[1]))), self.padding

    def layout_for(self, block: RenderBlock) -> TextLayout:
        """In-place layout: wrapped and sized for the block's box plus the
        free room around it."""
        x0, y0, x1, y1 = block.bbox
        width, height = x1 - x0, y1 - y0
        base_px = block.font_px
        room = block.room_below + block.room_above  # only the sum matters to the layout
        ratio = self.spacing_ratio(block.weight)
        key = ("inplace", tuple(block.lines), width, height, base_px, room, block.weight)
        return self._cached(
            self._layouts,
            key,
            lambda: fit_text(
                "\n".join(block.lines),
                width,
                height,
                self.measurer(block.weight),
                base_px,
                max_height=height + room,
                line_spacing=ratio,
                prefer_grow=True,
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
        layout = self._cached(
            self._layouts,
            key,
            lambda: fit_text(
                "\n".join(block.lines),
                width,
                int(font_px * ratio) + 1,
                self.measurer(block.weight),
                font_px,
                max_height=(zy1 - zy0) - 2 * margin,
                line_spacing=ratio,
                prefer_grow=True,
            ),
        )
        # Metrics of the size the layout settled on.
        metrics = self.metrics_at(layout.font_px, block.weight)
        text_w = min(width, max(metrics.horizontalAdvance(line) for line in layout.lines))
        anchor = block.anchor_y if block.anchor_y is not None else (y0 + y1) // 2
        text = subtitle_rect(block.zone, anchor, text_w, layout.height, block.position, margin)
        # The pill clears the descenders below and the ascenders above by the font's own measure.
        pill = text.adjusted(
            -font_px // 2, -max(2, metrics.descent() // 2), font_px // 2, max(2, metrics.descent() // 2)
        )
        return SubtitlePlacement(layout, text, pill, source)

    def place_chat(self, card: ChatCard) -> ChatPlacement:
        """Lay the card out: each line a bar in its speaker's colour, the
        name on a row of its own with the time at the right, and the words
        wrapped under it (a line with no speaker keeps the time at the right
        of its first row), stacked oldest first, padded and placed in the
        corner. The oldest lines go when the card would not fit the room."""
        px = card.font_px
        line_h = px * self.spacing_ratio(card.weight)
        pad, gap, radius, margin = round(px * 0.55), round(px * 0.25), round(px * 0.4), px
        bar_w = max(2, round(px * CHAT_BAR_SCALE))
        indent = bar_w + round(px * 0.5)  # from the bar to the text
        ax0, _, ax1, _ = card.area
        width = min(ax1 - ax0 - 2 * margin, max(5 * px, round((ax1 - ax0) * card.width)))
        inner = width - 2 * pad - indent  # the text column
        measure = self.measurer(card.weight)
        stamps = self.metrics_at(stamp_px(px), "regular")
        laid: list[tuple[ChatLine, int, list[str]]] = []  # (line, the stamp's width, rows)
        for line in card.lines:
            stamp_w = stamps.horizontalAdvance(line.stamp) + round(px * 0.4) if line.stamp else 0
            text_w = inner if line.speaker else inner - stamp_w  # with no name row the time shares the first row
            rows = [  # a screen read's page keeps its paragraphs
                row
                for paragraph in line.text.split("\n")
                for row in wrap_words(paragraph, max(px, text_w), lambda s: measure(s, px))
            ]
            laid.append((line, stamp_w, rows))

        def rows_of(entry: tuple[ChatLine, int, list[str]]) -> int:
            line, _, rows = entry
            return len(rows) + (1 if line.speaker else 0)

        def height_of(entries: list[tuple[ChatLine, int, list[str]]]) -> int:
            return int(2 * pad + sum(rows_of(e) for e in entries) * line_h + gap * max(0, len(entries) - 1)) + 1

        room_top, room_bottom = chat_room(card, margin)
        while len(laid) > 1 and height_of(laid) > room_bottom - room_top:
            del laid[0]  # the oldest line goes first; the newest is never dropped
        if height_of(laid) > room_bottom - room_top:  # one line alone too tall (a long page): cut, with a mark
            line, stamp_w, rows = laid[0]
            fit = max(1, int((room_bottom - room_top - 2 * pad) / line_h) - (1 if line.speaker else 0))
            laid[0] = (line, stamp_w, [*rows[: fit - 1], "…"])
        rect = chat_card_rect(card, width, height_of(laid), margin)
        entries: list[ChatEntry] = []
        top = float(rect.top() + pad)
        for line, stamp_w, rows in laid:  # oldest at the top, the newest last
            x, y = rect.left() + pad + indent, int(top)
            row_h = int(line_h) + 1
            whole = int(rows_of((line, stamp_w, rows)) * line_h) + 1
            bar = QRect(rect.left() + pad, y + round(px * 0.1), bar_w, whole - round(px * 0.3))
            name = QRect(x, y, inner - stamp_w, row_h) if line.speaker else QRect()
            stamp = QRect(x + inner - stamp_w, y, stamp_w, row_h) if stamp_w else QRect()
            text_y = y + int(line_h) if line.speaker else y
            text = QRect(x, text_y, inner if line.speaker else inner - stamp_w, int(len(rows) * line_h) + 1)
            entries.append(ChatEntry(line, bar, stamp, name, text, rows))
            top += rows_of((line, stamp_w, rows)) * line_h + gap
        return ChatPlacement(rect, entries, line_h, radius)

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

    def paint_blocks(self, p: QPainter, drawables: list[Drawable]) -> None:
        """Draw blocks and chat cards with `p`, which may target a window or
        any image, in list order. The texts of the subtitles go on after
        every background, so a band over one block's source line never
        covers another block's translation, whatever the order of the list;
        the chat cards go on last. (Something meant to lie under a band, as
        the settings preview's game line, is drawn by a call of its own
        before.)"""
        blocks = [d for d in drawables if isinstance(d, RenderBlock)]
        placements = self.place_subtitles(blocks)
        for i, block in enumerate(blocks):
            placed = placements.get(i)
            if placed is None:
                self._paint_block(p, block)
            else:
                self._paint_subtitle_background(p, block, placed)
        for i, placed in placements.items():
            self._paint_subtitle_text(p, blocks[i], placed)
        for card in drawables:
            if isinstance(card, ChatCard):
                self._paint_chat(p, card)

    def _paint_block(self, p: QPainter, block: RenderBlock) -> None:
        """A debug outline, or a block drawn on its own box."""
        if block.outline:
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

    def _paint_chat(self, p: QPainter, card: ChatCard) -> None:
        """The bands over the source lines, the card, then each line: its
        bar, the time at the right, the name and the words."""
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(PILL_COLOR)
        for box in card.covers:
            p.drawRoundedRect(_padded(box, *self._pads(box)), 6, 6)
        if not card.lines:
            return
        placed = self.place_chat(card)
        alpha = max(0, min(255, int(card.alpha)))
        p.setBrush(QColor(*CHAT_CARD_RGB, alpha))
        p.drawRoundedRect(placed.card, placed.radius, placed.radius)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, CHAT_BORDER_ALPHA * alpha // 255), 1))
        p.drawRoundedRect(QRectF(placed.card).adjusted(0.5, 0.5, -0.5, -0.5), placed.radius, placed.radius)  # crisp
        stamp_font = self.font_at(stamp_px(card.font_px), "regular")
        name_font = self.font_at(name_px(card.font_px), "bold")
        text_font = self.font_at(card.font_px, card.weight)
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        decoration = "shadow" if alpha < _CHAT_SHADOW_BELOW else "none"  # a faint card needs the text to carry itself
        line_h = placed.line_height
        fg = QColor(*card.fg)
        for entry in placed.entries:
            # A speaker's colour; a line with none, or a screen read's page (a title, no speaker index), the plain bar.
            colour = CHAT_BAR_PLAIN
            if entry.line.speaker and entry.line.speaker_index >= 0:
                colour = QColor(*CHAT_PALETTE[entry.line.speaker_index % len(CHAT_PALETTE)])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(colour)
            p.drawRoundedRect(QRectF(entry.bar), entry.bar.width() / 2, entry.bar.width() / 2)
            if entry.line.stamp:
                muted = QColor(*card.fg, CHAT_STAMP_ALPHA)
                self._draw_lines(p, [entry.line.stamp], entry.stamp, line_h, muted, decoration, stamp_font, right)
            if entry.line.speaker:
                self._draw_lines(p, [entry.line.speaker], entry.name, line_h, fg, decoration, name_font, left)
            self._draw_lines(p, entry.rows, entry.text, line_h, fg, decoration, text_font, left)

    def _draw_lines(
        self,
        p: QPainter,
        lines: list[str],
        area: QRect,
        line_h: float,
        fg: QColor,
        decoration: str,
        font: QFont,
        flags: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
    ) -> None:
        """Draw `lines` in `font` top to bottom, each in a row `line_h` tall
        (centred, unless `flags` say otherwise), with an outline, a drop
        shadow or nothing behind the text."""
        p.setFont(font)
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
