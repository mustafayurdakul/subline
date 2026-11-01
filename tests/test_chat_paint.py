"""The chat card: laid out in its corner above the strip, lines oldest
first, each with a bar in its speaker's colour, the name over the words
and the time at the right, words wrapped to the card, the bands over the
source lines, and the card drawn only when it has lines. Runs offscreen;
nothing reads glyph shapes, so a font-less runner passes too."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from gametl.overlay.paint import (
    CHAT_CORNERS,
    CHAT_PALETTE,
    BlockPainter,
    ChatCard,
    ChatLine,
    chat_card_rect,
)

AREA = (0, 0, 800, 450)
STRIP = (0, 340, 800, 450)
WIDTH, HEIGHT = 800, 450


@pytest.fixture
def painter(qapp: QApplication) -> BlockPainter:
    return BlockPainter()


def card(lines: list[tuple[str, str]], stamp: str = "", **kwargs) -> ChatCard:
    speakers = {name: i for i, name in enumerate(dict.fromkeys(name for name, _ in lines if name))}
    entries = [ChatLine(name, text, speakers.get(name, -1), stamp) for name, text in lines]
    return ChatCard(AREA, entries, **{"zone": STRIP, "font_px": 20, **kwargs})


def paint_rgba(painter: BlockPainter, *drawables) -> np.ndarray:
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
    image.fill(0)
    p = QPainter(image)
    try:
        painter.paint_blocks(p, list(drawables))
    finally:
        p.end()
    buffer = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(HEIGHT, image.bytesPerLine())
    return buffer[:, : WIDTH * 4].reshape(HEIGHT, WIDTH, 4).copy()


SAMPLE = [("Casey", "Nereye gidiyorsun?"), ("Alan", "Işıklar söndüğünde buradaydın."), ("Casey", "Sanki sinyal.")]


def test_the_card_sits_in_its_corner_above_the_strip(painter: BlockPainter) -> None:
    for corner in CHAT_CORNERS:
        placed = painter.place_chat(card(SAMPLE, corner=corner))
        rect = placed.card
        assert rect.width() == round(800 * 0.38)  # the share of the area's width
        assert rect.left() >= 0 and rect.right() <= 799
        if corner.endswith("left"):
            assert rect.left() == 20  # a margin of one font size in from the edge
        else:
            assert rect.right() == 800 - 20 - 1
        if corner.startswith("top"):
            assert rect.top() == 20
        else:
            assert rect.bottom() < STRIP[1]  # above the area read: never over the game's own subtitles
    # Without a strip in the lower half, a bottom corner is the area's bottom.
    placed = painter.place_chat(card(SAMPLE, corner="bottom-left", zone=(0, 0, 800, 450)))
    assert placed.card.bottom() == 450 - 20 - 1
    assert chat_card_rect(ChatCard(AREA, corner="top-right"), 100, 50, 10).topRight().x() == 800 - 10 - 1


def test_lines_run_oldest_to_newest(painter: BlockPainter) -> None:
    placed = painter.place_chat(card(SAMPLE))
    entries = placed.entries
    assert [e.line.text for e in entries] == [text for _, text in SAMPLE]
    assert entries[0].text.top() < entries[1].text.top() < entries[2].text.top()
    assert all(e.text.top() >= placed.card.top() and e.text.bottom() <= placed.card.bottom() for e in entries)
    # Every line has its bar beside it; a line without a speaker has no name row and its words start at the top.
    for entry in entries:
        assert entry.bar.right() < entry.text.left() and entry.bar.top() >= entry.name.top()
        assert entry.text.top() == entry.name.top() + int(placed.line_height)  # the name over the words
    (entry,) = painter.place_chat(card([("", "Hello.")])).entries
    assert entry.name.isEmpty() and entry.stamp.isEmpty() and entry.text.left() == placed.entries[0].name.left()
    assert entry.bar.right() < entry.text.left()


def test_the_time_sits_at_the_right_of_the_name_row(painter: BlockPainter) -> None:
    placed = painter.place_chat(card(SAMPLE, stamp="21:36:05"))
    for entry in placed.entries:
        assert entry.stamp.top() == entry.name.top() and entry.stamp.right() == entry.text.right()
        assert entry.name.right() < entry.stamp.left()  # the name is clipped before the time, never under it
        assert entry.text.width() == entry.name.width() + entry.stamp.width()  # the words take the whole row
    (plain,) = painter.place_chat(card([("", "Hello.")], stamp="21:36:05")).entries
    assert plain.stamp.top() == plain.text.top() and plain.text.right() < plain.stamp.left()  # on the first row
    assert plain.text.width() < painter.place_chat(card([("", "Hello.")])).entries[0].text.width()


def test_long_lines_wrap_to_the_card(painter: BlockPainter) -> None:
    long = "One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen."
    placed = painter.place_chat(card([("Alan", long)]))
    (entry,) = placed.entries
    assert len(entry.rows) > 1 and " ".join(entry.rows) == long
    measure = painter.measurer("semibold")
    assert all(measure(row, 20) <= entry.text.width() + 1 for row in entry.rows)
    assert placed.card.height() > painter.place_chat(card([("Alan", "Short.")])).card.height()


def test_a_wide_name_stays_inside_the_card(painter: BlockPainter) -> None:
    placed = painter.place_chat(card([("Commander Shepard Vakarian", "We should go now.")], width=0.3))
    (entry,) = placed.entries
    assert entry.name.width() == entry.text.width() > 0  # the name's row spans the words' column
    assert entry.text.top() >= entry.name.top() + int(placed.line_height)
    assert entry.text.right() <= placed.card.right() and entry.name.right() <= placed.card.right()
    assert placed.card.bottom() >= entry.text.bottom()


def test_the_oldest_lines_go_when_the_card_would_not_fit(painter: BlockPainter) -> None:
    many = [(("Alan", "Casey")[i % 2], f"Line number {i} of a long conversation that goes on.") for i in range(12)]
    placed = painter.place_chat(card(many, corner="bottom-left"))
    assert placed.card.top() >= 20 and placed.card.bottom() < STRIP[1]  # fits between the margin and the strip
    assert 0 < len(placed.entries) < 12
    assert [e.line.text for e in placed.entries] == [text for _, text in many[-len(placed.entries) :]]  # newest kept


def test_a_faint_card_loses_its_border_and_shadows_its_text(painter: BlockPainter) -> None:
    full = paint_rgba(painter, card(SAMPLE, alpha=255))
    faint = paint_rgba(painter, card(SAMPLE, alpha=0))
    rect = painter.place_chat(card(SAMPLE)).card
    assert full[rect.top(), rect.center().x(), 3] > 0  # the hairline on the full card
    assert faint[rect.top(), rect.center().x(), 3] == 0  # none on the invisible one
    assert faint[rect.center().y(), rect.left() + 3, 3] == 0  # and no fill (inside the card, left of the bars)
    assert full[rect.center().y(), rect.left() + 3, 3] == 255
    text = painter.place_chat(card(SAMPLE)).entries[-1].text
    assert faint[text.top() : text.bottom(), text.left() : text.right(), 3].max() > 0  # the text still shows


def test_the_card_the_names_and_the_bands_are_drawn(painter: BlockPainter) -> None:
    drawn = card(SAMPLE, alpha=200, covers=[(300, 380, 500, 400)])
    placed = painter.place_chat(drawn)
    image = paint_rgba(painter, drawn)
    rect = placed.card
    assert image[rect.center().y(), rect.center().x(), 3] >= 200  # the card, at its opacity
    assert image[390, 400, 3] >= 230  # the band over the source line, dark whatever the card's opacity
    assert image[10, 400, 3] == 0  # nothing outside
    # Each line's bar is painted in its speaker's palette colour (BGRA in the buffer).
    for entry, index in zip(placed.entries, (0, 1, 0), strict=True):
        b, g, r = image[entry.bar.center().y(), entry.bar.center().x(), :3]
        assert (r, g, b) == CHAT_PALETTE[index]


def test_the_card_is_frosted_glass_when_it_has_the_frame(painter: BlockPainter) -> None:
    from gametl.overlay.paint import CHAT_GLASS_SCALE

    # A frame thumbnail: red on the left half, green on the right (BGR), as the pipeline would blur it.
    backdrop = np.zeros((HEIGHT // CHAT_GLASS_SCALE, WIDTH // CHAT_GLASS_SCALE, 3), dtype=np.uint8)
    backdrop[:, : backdrop.shape[1] // 2] = (0, 0, 255)
    backdrop[:, backdrop.shape[1] // 2 :] = (0, 255, 0)
    glass = card(SAMPLE, alpha=255, backdrop=backdrop, width=0.9)
    flat = card(SAMPLE, alpha=255)
    rect = painter.place_chat(glass).card
    image = paint_rgba(painter, glass)
    left = image[rect.center().y(), rect.left() + 3]
    right = image[rect.center().y(), rect.right() - 3]
    assert left[3] == 255 and left[2] > left[1] + 40  # the scene shows through the tint: red on the left...
    assert right[1] > right[2] + 40  # ...green on the right
    assert image[rect.top(), rect.center().x(), :3].max() < 120  # no hairline on glass, the tint only
    plain = paint_rgba(painter, flat)
    assert tuple(plain[rect.center().y(), rect.left() + 3, :3]) == (16, 12, 12)  # the flat card, BGR
    assert glass != flat and card(SAMPLE, backdrop=backdrop) == card(
        SAMPLE, backdrop=backdrop * 0
    )  # the array is not compared
    assert card(SAMPLE, backdrop_version=1) != card(SAMPLE, backdrop_version=2)  # the version is


def test_an_empty_card_draws_nothing_but_its_bands(painter: BlockPainter) -> None:
    assert paint_rgba(painter, ChatCard(AREA, zone=STRIP))[:, :, 3].max() == 0
    image = paint_rgba(painter, ChatCard(AREA, zone=STRIP, covers=[(300, 380, 500, 400)]))
    assert image[390, 400, 3] > 0 and image[100, 100, 3] == 0
