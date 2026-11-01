"""The chat card: laid out in its corner above the strip, lines oldest
first, the time and the name in front of the words, names in their
speaker's colour, words wrapped to the card, the bands over the source
lines, and the card drawn only when it has lines. Runs offscreen; nothing
reads glyph shapes, so a font-less runner passes too."""

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
    # A line without a speaker has no name box and its words start at the card's padding.
    (entry,) = painter.place_chat(card([("", "Hello.")])).entries
    assert entry.name.isEmpty() and entry.stamp.isEmpty() and entry.text.left() == placed.entries[0].name.left()


def test_the_time_goes_in_front_of_the_name(painter: BlockPainter) -> None:
    placed = painter.place_chat(card(SAMPLE, stamp="21:36:05", width=0.6))
    for entry in placed.entries:
        assert entry.stamp.left() == placed.card.left() + round(20 * 0.55)
        assert entry.stamp.right() < entry.name.left() < entry.text.left()  # time, name, words
        assert entry.stamp.top() == entry.name.top() == entry.text.top()
    (plain,) = painter.place_chat(card([("", "Hello.")], stamp="21:36:05", width=0.6)).entries
    assert plain.name.isEmpty() and plain.stamp.right() < plain.text.left()  # no name: time, then the words
    with_time = painter.place_chat(card(SAMPLE, stamp="21:36:05", width=0.6)).entries[0].text.width()
    without = painter.place_chat(card(SAMPLE, width=0.6)).entries[0].text.width()
    assert with_time < without  # the words give way to the time
    # On a narrow card the time and the name together would leave the words no room: the name takes a row.
    (narrow,) = painter.place_chat(card(SAMPLE[:1], stamp="21:36:05", width=0.25)).entries
    assert narrow.stamp.right() < narrow.name.left() and narrow.text.top() > narrow.name.top()


def test_long_lines_wrap_to_the_card(painter: BlockPainter) -> None:
    long = "One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen."
    placed = painter.place_chat(card([("Alan", long)]))
    (entry,) = placed.entries
    assert len(entry.rows) > 1 and " ".join(entry.rows) == long
    measure = painter.measurer("semibold")
    assert all(measure(row, 20) <= entry.text.width() + 1 for row in entry.rows)
    assert placed.card.height() > painter.place_chat(card([("Alan", "Short.")])).card.height()


def test_a_wide_name_takes_a_row_of_its_own(painter: BlockPainter) -> None:
    placed = painter.place_chat(card([("Commander Shepard Vakarian", "We should go now.")], width=0.3))
    (entry,) = placed.entries
    assert entry.name.width() == entry.text.width() > 0  # the name spans the card, the words start under it
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
    assert faint[rect.center().y(), rect.center().x(), 3] == 0  # and no fill
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
    # The newest speaker's name is painted in its palette colour (BGRA in the buffer).
    name = placed.entries[-1].name
    patch = image[name.top() : name.bottom(), name.left() : name.right()]
    r, g, b = CHAT_PALETTE[0]
    tinted = patch[(patch[:, :, 3] > 0) & (np.abs(patch[:, :, 2].astype(int) - r) < 40)]
    assert len(tinted) > 0 and all(abs(int(px[1]) - g) < 60 and abs(int(px[0]) - b) < 60 for px in tinted[:50])


def test_an_empty_card_draws_nothing_but_its_bands(painter: BlockPainter) -> None:
    assert paint_rgba(painter, ChatCard(AREA, zone=STRIP))[:, :, 3].max() == 0
    image = paint_rgba(painter, ChatCard(AREA, zone=STRIP, covers=[(300, 380, 500, 400)]))
    assert image[390, 400, 3] > 0 and image[100, 100, 3] == 0
