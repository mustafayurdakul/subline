from __future__ import annotations

import numpy as np

from gametl.ocr.base import TextLine
from gametl.tracking.filters import LineFilter


def line(text: str, x0: int, y0: int, x1: int, y1: int) -> TextLine:
    quad = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)
    return TextLine(text, quad, 0.9)


def test_empty_filter_passes_everything() -> None:
    lines = [line("a", 0, 0, 10, 10)]
    assert LineFilter.compile().apply(lines) == lines


def test_zone_drops_lines_whose_centre_is_inside() -> None:
    f = LineFilter.compile(zones=[(0, 0, 300, 100)])
    hud = line("HP 87/100", 20, 40, 240, 70)
    subtitle = line("Stay close.", 300, 620, 900, 660)
    straddling = line("edge", 250, 80, 400, 110)  # centre (325, 95): outside
    assert f.apply([hud, subtitle, straddling]) == [subtitle, straddling]


def test_patterns_drop_matching_text() -> None:
    f = LineFilter.compile(patterns=[r"^\s*[\d:./ ]+\s*$", r"^press "])
    keep = line("Stay close.", 300, 620, 900, 660)
    timer = line("12:45", 0, 0, 50, 20)
    prompt = line("Press A to continue", 0, 0, 50, 20)
    assert f.apply([keep, timer, prompt]) == [keep]
