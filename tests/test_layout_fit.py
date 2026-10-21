from __future__ import annotations

from gametl.layout.fit import ellipsize, fit_text, wrap_words


def measure(text: str, px: int) -> float:
    """Fake metrics: every character is half the font size wide."""
    return len(text) * px * 0.5


def test_wrap_words_greedy_and_overflowing_word() -> None:
    width_of = lambda s: len(s)  # noqa: E731
    assert wrap_words("aa bb cc dd", 5, width_of) == ["aa bb", "cc dd"]
    assert wrap_words("supercalifragilistic is long", 8, width_of) == ["supercalifragilistic", "is long"]
    assert wrap_words("", 10, width_of) == [""]


def test_ellipsize() -> None:
    assert ellipsize("short", 100, len) == "short"
    assert ellipsize("a rather long line", 8, len) == "a rathe…"


def test_text_that_fits_is_unchanged() -> None:
    # 20 chars at 32 px = 320 wide; box 400x40
    layout = fit_text("twenty characters!!!", 400, 40, measure, base_px=32)
    assert layout.lines == ["twenty characters!!!"]
    assert layout.font_px == 32
    assert layout.grown is False and layout.truncated is False


def test_slightly_long_text_shrinks_within_the_box() -> None:
    # 26 chars: needs 416 at 32 px; fits one line at 30 px (390).
    layout = fit_text("twenty-six characters here", 400, 40, measure, base_px=32)
    assert layout.lines == ["twenty-six characters here"]
    assert 28 <= layout.font_px < 32


def test_much_longer_text_grows_into_free_space_at_full_size() -> None:
    text = "this translation is roughly twice as long as the source line was"
    layout = fit_text(text, 400, 40, measure, base_px=32, max_height=120)
    assert layout.font_px == 32
    assert len(layout.lines) == 3
    assert layout.grown is True
    assert layout.height <= 120
    assert all(measure(line, 32) <= 400 for line in layout.lines)


def test_without_free_space_text_shrinks_further() -> None:
    text = "this translation is roughly twice as long as the source line was"
    layout = fit_text(text, 400, 40, measure, base_px=32, max_height=None)
    assert layout.grown is False
    assert layout.truncated is False
    assert layout.height <= 40
    assert layout.font_px < 32 * 0.72


def test_hopeless_text_is_truncated_at_minimum_size() -> None:
    text = " ".join(["word"] * 200)
    layout = fit_text(text, 200, 20, measure, base_px=16, min_px=10)
    assert layout.truncated is True
    assert layout.font_px == 10
    assert layout.lines[-1].endswith("…")
    assert layout.height <= 20 + 1


def test_explicit_newlines_are_kept() -> None:
    layout = fit_text("first line\nsecond line", 400, 80, measure, base_px=30)
    assert layout.lines == ["first line", "second line"]
    assert layout.font_px == 30
