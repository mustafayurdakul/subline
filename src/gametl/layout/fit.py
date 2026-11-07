"""Fit translated text into the box of the source text.

Pure functions: text measurement is injected (`measure(text, font_px) ->
width`), so the algorithm is testable without a GUI toolkit.

Preference order when the translation is longer than the source:
1. keep the source font size and wrap, letting the box grow into the free
   space the caller reports as `max_height`, so every line renders at one
   size;
2. shrink the font one pixel at a time, down to `shrink_floor` of the
   source size, until it fits the source box, wrapping as needed;
3. otherwise grow the box at the largest of those sizes that fits
   `max_height`;
4. shrink further, down to `min_px`;
5. truncate with an ellipsis.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

Measure = Callable[[str, int], float]


@dataclass(slots=True)
class TextLayout:
    lines: list[str]
    font_px: int
    line_height: float
    height: int  # total height the lines need
    grown: bool  # needs more than the source box height
    truncated: bool


def _break(word: str, max_width: float, width_of: Callable[[str], float]) -> list[str]:
    """`word` as pieces no wider than `max_width`, cut between characters;
    a single character wider than that stands alone."""
    if width_of(word) <= max_width:
        return [word]
    pieces: list[str] = []
    current = ""
    for char in word:
        if current and width_of(current + char) > max_width:
            pieces.append(current)
            current = char
        else:
            current += char
    return [*pieces, current]


def wrap_words(text: str, max_width: float, width_of: Callable[[str], float]) -> list[str]:
    """Greedy word wrap. A word wider than `max_width` is cut between
    characters: text without spaces, as Japanese and Chinese are written, is
    one word, and would otherwise run past both sides of the box."""
    words = [piece for word in text.split() for piece in _break(word, max_width, width_of)]
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if width_of(candidate) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def truncate_with_ellipsis(text: str, max_width: float, width_of: Callable[[str], float]) -> str:
    """Always ends with an ellipsis, trimmed to fit `max_width`."""
    while text and width_of(text + "…") > max_width:
        text = text[:-1].rstrip()
    return text + "…"


def fit_text(
    text: str,
    width: int,
    height: int,
    measure: Measure,
    base_px: int,
    max_height: int | None = None,
    min_px: int = 10,
    shrink_floor: float = 0.72,
    line_spacing: float = 1.15,
) -> TextLayout:
    """Lay `text` out in a box `width` wide and `height` tall, starting from
    font size `base_px` (the source text's size). Explicit newlines are kept
    as paragraph breaks. `max_height` is how tall the box may become."""
    paragraphs = text.split("\n")
    limit = max(height, max_height or 0)
    base_px = max(min_px, int(base_px))
    floor_px = max(min_px, round(base_px * shrink_floor))

    def layout_at(px: int) -> tuple[list[str], float, float]:
        lines: list[str] = []
        for paragraph in paragraphs:
            lines.extend(wrap_words(paragraph, width, lambda s: measure(s, px)))
        line_h = px * line_spacing
        return lines, line_h, len(lines) * line_h

    # 1. Keep the size and wrap, when the box may grow enough to hold the lines.
    lines, line_h, total = layout_at(base_px)
    if total <= limit:
        return TextLayout(lines, base_px, line_h, math.ceil(total), total > height, False)

    # 2. Shrink a little, one pixel at a time below the size step 1 tried,
    #    until the text fits the source box; remember the largest size that
    #    would fit if the box grew.
    grow: tuple[list[str], int, float, float] | None = None
    for px in range(base_px - 1, floor_px - 1, -1):
        lines, line_h, total = layout_at(px)
        if total <= height:
            return TextLayout(lines, px, line_h, math.ceil(total), False, False)
        if grow is None and total <= limit:
            grow = (lines, px, line_h, total)
    # 3. Grow the box at that size.
    if grow is not None:
        lines, px, line_h, total = grow
        return TextLayout(lines, px, line_h, math.ceil(total), True, False)

    # 4. Shrink further, down to the minimum size.
    for px in range(floor_px - 1, min_px - 1, -1):
        lines, line_h, total = layout_at(px)
        if total <= limit:
            return TextLayout(lines, px, line_h, math.ceil(total), total > height, False)

    # 5. Still too tall: keep the lines that fit and end them with an ellipsis.
    lines, line_h, total = layout_at(min_px)
    n_fit = max(1, int(limit // line_h))
    if len(lines) > n_fit:
        lines = lines[:n_fit]
        lines[-1] = truncate_with_ellipsis(lines[-1], width, lambda s: measure(s, min_px))
    total = len(lines) * line_h
    return TextLayout(lines, min_px, line_h, math.ceil(total), total > height, True)
