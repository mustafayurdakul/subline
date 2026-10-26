from __future__ import annotations

from gametl.app.config import NO_LETTERS_PATTERN
from gametl.tracking.filters import LineFilter
from tests.helpers import line


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


def test_short_lines_need_confidence() -> None:
    f = LineFilter.compile()  # the short-line rule is on by default
    assert f  # so the filter is never a no-op
    fragment = line("l", 0, 0, 20, 20, confidence=0.6)  # a stroke read as a letter
    glyph = line("Go!", 0, 0, 40, 20, confidence=0.5)  # two letters, unsure
    sure = line("No.", 0, 0, 40, 20, confidence=0.95)
    word = line("Hey", 0, 0, 40, 20, confidence=0.5)  # three letters: the rule does not apply
    assert f.apply([fragment, glyph, sure, word]) == [sure, word]
    assert LineFilter.compile(short_confidence=0).apply([fragment, glyph]) == [fragment, glyph]  # off


def test_default_pattern_drops_lines_without_letters() -> None:
    f = LineFilter.compile(patterns=[NO_LETTERS_PATTERN])
    dropped = [line("12:45", 0, 0, 50, 20), line("87/100", 0, 0, 50, 20), line("- -", 0, 0, 50, 20)]
    kept = [line("Press A", 0, 0, 50, 20), line("5 dakika", 0, 0, 50, 20), line("こんにちは", 0, 0, 50, 20)]
    assert f.apply(dropped + kept) == kept
