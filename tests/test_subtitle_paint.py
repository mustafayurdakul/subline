"""Subtitle painting into an image: line heights from the font's metrics
so descenders fit, the three backgrounds, pill opacity and weights.
Runs offscreen."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from gametl.overlay.paint import BlockPainter, RenderBlock

ZONE = (0, 200, 400, 300)
WIDTH, HEIGHT = 400, 300


@pytest.fixture
def overlay(qapp: QApplication) -> BlockPainter:
    return BlockPainter()


def subtitle(lines: list[str], **kwargs) -> RenderBlock:
    return RenderBlock((120, 262, 280, 282), lines, style="subtitle", zone=ZONE, font_px=24, **kwargs)


def paint_rgba(overlay: BlockPainter, block: RenderBlock) -> np.ndarray:
    """The painted image as (H, W, 4) BGRA."""
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        overlay.paint_blocks(painter, [block])
    finally:
        painter.end()
    buffer = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(HEIGHT, image.bytesPerLine())
    return buffer[:, : WIDTH * 4].reshape(HEIGHT, WIDTH, 4).copy()


def paint(overlay: BlockPainter, block: RenderBlock) -> np.ndarray:
    """Alpha channel of the painted image."""
    return paint_rgba(overlay, block)[:, :, 3]


def test_line_height_comes_from_the_font_so_descenders_fit(overlay: BlockPainter) -> None:
    placed = overlay.place_subtitle(subtitle(["Nereye gidiyorsun, jyg?"]))
    metrics = overlay.metrics_at(placed.layout.font_px)
    assert placed.layout.line_height >= metrics.height()  # ascent + descent + leading, not a flat 1.15
    assert placed.text.height() >= metrics.height()
    assert placed.pill.bottom() >= placed.text.bottom() + 2  # room below the descenders
    # The ratio is whatever the font engine reports (1.0 on a runner without real fonts), never below it.
    assert overlay.spacing_ratio() >= metrics.height() / placed.layout.font_px - 1e-9

    two = overlay.place_subtitle(subtitle(["first line", "second line"]))
    assert two.layout.line_height * 2 <= two.text.height() + 1


def test_in_place_layout_uses_the_same_metrics(overlay: BlockPainter) -> None:
    layout = overlay.layout_for(RenderBlock((0, 0, 300, 40), ["gjpqy"]))
    assert layout.line_height >= overlay.metrics_at(layout.font_px).height()


def test_pill_shadow_and_none_backgrounds(overlay: BlockPainter) -> None:
    pill = paint(overlay, subtitle(["Yakın dur."], background="pill", hide_source=False))
    shadow = paint(overlay, subtitle(["Yakın dur."], background="shadow", hide_source=False))
    bare = paint(overlay, subtitle(["Yakın dur."], background="none", hide_source=False))
    assert (pill > 0).sum() > (shadow > 0).sum() > 0  # a box covers far more than text with a shadow
    assert (bare > 0).sum() > 0
    # The shadow lies below and right of the text: its lowest painted row is deeper than the bare text's.
    assert np.nonzero(shadow.any(axis=1))[0].max() >= np.nonzero(bare.any(axis=1))[0].max()


def test_pill_opacity_is_the_setting(overlay: BlockPainter) -> None:
    block = subtitle(["Yakın dur."], background="pill", pill_alpha=100, hide_source=False)
    placed = overlay.place_subtitle(block)
    alpha = paint(overlay, block)
    x, y = placed.pill.left() + 4, placed.pill.center().y()  # inside the box, in the margin left of the text
    assert alpha[y, x] == 100


def test_source_band_hides_the_original_whatever_the_pill_opacity(overlay: BlockPainter) -> None:
    # Text at the bottom of the zone, source line at its top: two shapes, the band fully dark.
    block = RenderBlock(
        (120, 205, 280, 225), ["Yakın dur."], style="subtitle", zone=ZONE, font_px=24, pill_alpha=60, position="bottom"
    )
    placed = overlay.place_subtitle(block)
    assert not placed.pill.intersects(placed.source)
    alpha = paint(overlay, block)
    assert alpha[placed.source.center().y(), placed.source.center().x()] == 230


def test_weights_are_distinct_fonts_and_bold_measures_wider(overlay: BlockPainter) -> None:
    assert overlay.font_at(24, "bold").weight() == QFont.Weight.Bold
    assert overlay.font_at(24, "semibold").weight() == QFont.Weight.DemiBold
    assert overlay.font_at(24).weight() == QFont.Weight.Normal
    regular = overlay.measurer("regular")("Nereye gidiyorsun?", 24)
    bold = overlay.measurer("bold")("Nereye gidiyorsun?", 24)
    assert bold > regular
    placed = overlay.place_subtitle(subtitle(["Nereye gidiyorsun?"], weight="bold"))
    assert placed.text.width() >= int(bold) - 1
