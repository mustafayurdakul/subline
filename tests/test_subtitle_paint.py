"""Overlay painting into an image: subtitle placement and stacking, line
heights from the font's metrics so descenders fit, the three backgrounds,
the band over the source line, pill opacity, weights, the in-place layout,
and the overlay window repainting only when its blocks change. Runs
offscreen, so CI runs it."""

from __future__ import annotations

import os
from itertools import pairwise

import numpy as np
import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from gametl.layout.style import font_px_for
from gametl.overlay.paint import BlockPainter, RenderBlock, subtitle_rect
from gametl.overlay.window import OverlayWindow

ZONE = (0, 200, 400, 300)
WIDTH, HEIGHT = 400, 300


@pytest.fixture
def overlay(qapp: QApplication) -> BlockPainter:
    return BlockPainter()


def subtitle(lines: list[str], **kwargs) -> RenderBlock:
    return RenderBlock((120, 262, 280, 282), lines, style="subtitle", zone=ZONE, font_px=24, **kwargs)


def paint_rgba(overlay: BlockPainter, *blocks: RenderBlock) -> np.ndarray:
    """The painted image as (H, W, 4) BGRA."""
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        overlay.paint_blocks(painter, list(blocks))
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
    assert placed.layout.line_height >= metrics.height()  # ascent + descent, not a flat 1.15
    assert placed.text.height() >= metrics.height()
    assert placed.pill.bottom() >= placed.text.bottom() + 2  # room below the descenders
    # The ratio is whatever the font engine reports (1.0 on a runner without real fonts), never below it.
    assert overlay.spacing_ratio() >= metrics.height() / placed.layout.font_px - 1e-9

    two = overlay.place_subtitle(subtitle(["first line", "second line"]))
    assert two.layout.line_height * 2 <= two.text.height() + 1


def test_subtitle_rect_positions_and_clamps() -> None:
    zone = (100, 600, 1100, 700)  # 1000 wide, 100 tall
    r = subtitle_rect(zone, anchor_y=650, text_w=400, text_h=40, position="source")
    assert (r.left(), r.top(), r.width(), r.height()) == (400, 630, 400, 40)  # centred, on the source line
    r = subtitle_rect(zone, anchor_y=650, text_w=400, text_h=40, position="bottom")
    assert r.top() == 700 - 12 - 40
    r = subtitle_rect(zone, anchor_y=650, text_w=400, text_h=40, position="center")
    assert r.top() == 630
    r = subtitle_rect(zone, anchor_y=605, text_w=400, text_h=40, position="source")  # would poke out at the top
    assert r.top() == 612


def test_in_place_layout_uses_the_same_metrics(overlay: BlockPainter) -> None:
    layout = overlay.layout_for(RenderBlock((0, 0, 300, 40), ["gjpqy"], font_px=font_px_for(40)))
    assert layout.line_height >= overlay.metrics_at(layout.font_px).height()


def test_in_place_layout_fits_the_width(overlay: BlockPainter) -> None:
    block = RenderBlock((0, 0, 300, 60), ["A fairly long translated subtitle line", "second"], font_px=font_px_for(30))
    layout = overlay.layout_for(block)
    assert all(overlay.measurer("regular")(line, layout.font_px) <= 300 for line in layout.lines)
    assert layout.font_px >= 6
    assert overlay.layout_for(block) is layout  # cached
    short = overlay.layout_for(RenderBlock((0, 0, 1000, 50), ["Hi"], font_px=font_px_for(50)))
    assert short.font_px == font_px_for(50) == int(50 * 0.8)  # room to spare: the caller's size, kept


def test_a_new_font_drops_the_cached_layouts(overlay: BlockPainter) -> None:
    block = RenderBlock((0, 0, 300, 40), ["gjpqy"], font_px=24)
    layout = overlay.layout_for(block)
    overlay.set_font("Another Family")
    assert overlay.layout_for(block) is not layout


def test_pill_shadow_and_none_backgrounds(overlay: BlockPainter) -> None:
    pill = paint(overlay, subtitle(["Yakın dur."], background="pill", hide_source=False))
    shadow = paint(overlay, subtitle(["Yakın dur."], background="shadow", hide_source=False))
    bare = paint(overlay, subtitle(["Yakın dur."], background="none", hide_source=False))
    assert (pill > 0).sum() > (shadow > 0).sum() > 0  # a box covers far more than text with a shadow
    assert (bare > 0).sum() > 0
    # The shadow lies below and right of the text: its lowest painted row is deeper than the bare text's.
    assert np.nonzero(shadow.any(axis=1))[0].max() >= np.nonzero(bare.any(axis=1))[0].max()


def test_text_on_the_pill_has_no_outline(overlay: BlockPainter) -> None:
    block = subtitle(["Yakın dur."], background="pill", pill_alpha=100, hide_source=False)
    placed = overlay.place_subtitle(block)
    rgba = paint_rgba(overlay, block)
    box = rgba[placed.pill.top() : placed.pill.bottom() + 1, placed.pill.left() : placed.pill.right() + 1]
    dark_and_solid = (box[:, :, :3].max(axis=2) < 60) & (box[:, :, 3] > 150)  # an outline pixel over the pill
    assert not dark_and_solid.any()
    assert (box[:, :, :3].min(axis=2) > 200).any()  # the letters are there


def test_bare_text_has_an_outline(overlay: BlockPainter) -> None:
    block = subtitle(["Yakın dur."], background="none", hide_source=False)
    placed = overlay.place_subtitle(block)
    rgba = paint_rgba(overlay, block)
    box = rgba[placed.text.top() : placed.text.bottom() + 1, placed.text.left() : placed.text.right() + 1]
    dark_and_solid = (box[:, :, :3].max(axis=2) < 60) & (box[:, :, 3] > 150)  # the outline round the white letters
    assert dark_and_solid.any()


def test_in_place_pill_text_has_no_outline_either(overlay: BlockPainter) -> None:
    block = RenderBlock((120, 230, 280, 254), ["Yakın dur."], style="pill", font_px=24)
    rgba = paint_rgba(overlay, block)
    box = rgba[228:257, 116:285]
    # The box is PILL_COLOR (black, alpha 230). An outline would sit on top of it as a darker,
    # more opaque halo around the letters; the letters' own edges blend towards white instead.
    halo = (box[:, :, :3].max(axis=2) < 60) & (box[:, :, 3] > 240)
    assert not halo.any()
    assert (box[:, :, :3].min(axis=2) > 200).any()  # the letters are there


def at_source(bbox, **kwargs) -> RenderBlock:
    """A subtitle block positioned on its source line, the original left visible."""
    kwargs.setdefault("hide_source", False)
    kwargs.setdefault("position", "source")
    return RenderBlock(bbox, ["Yakın dur."], style="subtitle", zone=ZONE, font_px=24, **kwargs)


def test_pill_is_sized_by_the_text_not_the_source_box(overlay: BlockPainter) -> None:
    narrow, wide = at_source((180, 262, 220, 282)), at_source((20, 262, 380, 282))
    assert overlay.place_subtitle(narrow).pill == overlay.place_subtitle(wide).pill
    assert np.array_equal(paint(overlay, narrow), paint(overlay, wide))  # no band, so the same pill
    covered = paint(overlay, at_source((20, 262, 380, 282), hide_source=True))
    assert (covered > 0).sum() > (paint(overlay, wide) > 0).sum()  # the band over the wide source line joins the pill


def test_a_held_anchor_places_the_subtitle_not_the_box(overlay: BlockPainter) -> None:
    first = at_source((120, 262, 280, 282))
    moved, held = at_source((120, 240, 280, 260)), at_source((120, 240, 280, 260), anchor_y=272)
    assert overlay.place_subtitle(held).text == overlay.place_subtitle(first).text  # where the line was first seen
    assert overlay.place_subtitle(moved).text != overlay.place_subtitle(first).text


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


@pytest.mark.parametrize("position", ["source", "bottom"])
def test_band_merged_into_a_light_pill_still_hides_the_original(overlay: BlockPainter, position: str) -> None:
    # A wide source line in a thin zone: the pill and the band overlap and are drawn as one shape.
    block = at_source((20, 262, 380, 282), hide_source=True, pill_alpha=60, position=position)
    placed = overlay.place_subtitle(block)
    assert placed.pill.intersects(placed.source)
    alpha = paint(overlay, block)
    assert alpha[placed.source.center().y(), placed.source.left() + 8] == 230  # over the source, outside the text
    # The rest of the pill keeps the opacity chosen: only the part over the source line is darkened.
    below = placed.pill.bottom() - 1
    assert below > placed.source.bottom()
    assert alpha[below, placed.pill.left() + 4] == 60


def test_weights_are_distinct_fonts_and_bold_measures_wider(overlay: BlockPainter) -> None:
    assert overlay.font_at(24, "bold").weight() == QFont.Weight.Bold
    assert overlay.font_at(24, "semibold").weight() == QFont.Weight.DemiBold
    assert overlay.font_at(24).weight() == QFont.Weight.Normal
    regular = overlay.measurer("regular")("Nereye gidiyorsun?", 24)
    bold = overlay.measurer("bold")("Nereye gidiyorsun?", 24)
    if QFontDatabase.families():
        assert bold > regular
        placed = overlay.place_subtitle(subtitle(["Nereye gidiyorsun?"], weight="bold"))
        assert placed.text.width() >= int(bold) - 1
    else:  # the offscreen platform on Windows knows no fonts: every weight measures alike, a full em per glyph
        assert bold == regular


STACK_ZONE = (0, 100, 400, 300)


def shown_together(position: str, **kwargs) -> tuple[RenderBlock, RenderBlock]:
    """Two subtitle lines on screen at once, far enough apart to be two
    blocks: (the upper, the lower)."""
    common = {"style": "subtitle", "zone": STACK_ZONE, "font_px": 24, "position": position, **kwargs}
    upper = RenderBlock((60, 200, 340, 222), ["Nereye gidiyorsun?"], **common)
    lower = RenderBlock((80, 232, 320, 254), ["Yakın dur."], **common)
    return upper, lower


@pytest.mark.parametrize("position", ["bottom", "center"])
def test_subtitles_shown_together_are_stacked(overlay: BlockPainter, position: str) -> None:
    upper, lower = shown_together(position)
    placed = overlay.place_subtitles([lower, upper])  # the source lines decide the order, not the list
    top, bottom = placed[1], placed[0]
    assert not top.pill.intersects(bottom.pill)
    assert top.pill.bottom() < bottom.pill.top()  # the upper source line stays on top
    assert top.pill.top() >= STACK_ZONE[1]  # a stack that fits stays inside the zone
    if position == "bottom":
        assert bottom.text == overlay.place_subtitle(lower).text  # the lowest stays where one subtitle goes
    else:
        middle = (top.pill.top() + bottom.pill.bottom()) / 2
        assert abs(middle - (STACK_ZONE[1] + STACK_ZONE[3]) / 2) <= 1  # the stack is centred


def three_lines(zone: tuple[int, int, int, int], **kwargs) -> list[RenderBlock]:
    """Three subtitle lines on screen at once, each its own block."""
    common = {"style": "subtitle", "zone": zone, "font_px": 24, **kwargs}
    return [RenderBlock((60, y, 340, y + 20), [f"line {y}"], **common) for y in (5, 35, 65)]


def test_a_stack_taller_than_the_zone_rises_above_it(overlay: BlockPainter) -> None:
    zone = (0, 240, 400, 300)  # room for one line, not three
    blocks = three_lines(zone)
    placed = overlay.place_subtitles(blocks)
    pills = [placed[i].pill for i in range(3)]
    assert all(a.bottom() < b.top() for a, b in pairwise(pills))
    assert placed[2].text == overlay.place_subtitle(blocks[2]).text  # the lowest line keeps its place
    assert pills[0].top() < zone[1]

    placed = overlay.place_subtitles(three_lines((0, 0, 400, 60)))  # a strip at the top of the window
    pills = [placed[i].pill for i in range(3)]
    assert all(a.bottom() < b.top() for a, b in pairwise(pills))
    assert pills[0].top() == 0  # never past the window's top edge


def test_a_tall_stack_at_center_keeps_its_foot_in_the_zone(overlay: BlockPainter) -> None:
    zone = (0, 240, 400, HEIGHT)  # room for one line, down to the window's bottom edge
    placed = overlay.place_subtitles(three_lines(zone, position="center"))
    pills = [placed[i].pill for i in range(3)]
    assert all(a.bottom() < b.top() for a, b in pairwise(pills))
    assert pills[2].top() + pills[2].height() <= zone[3]  # the lowest line is not pushed off the window
    assert pills[0].top() < zone[1]  # the stack rises above the zone instead


@pytest.mark.parametrize("position", ["bottom", "source"])
def test_a_band_never_covers_a_translation_stacked_above(overlay: BlockPainter, position: str) -> None:
    upper, lower = shown_together(position, hide_source=True)
    if position == "source":
        # On its own line, the upper translation reaches the band below only when it wraps.
        upper.lines = ["Nereye gidiyorsun? Işıklar söndüğünde buradaydın, hatırlamıyor musun?"]
        upper.background = lower.background = "shadow"
    placed = overlay.place_subtitles([upper, lower])
    band, text = placed[1].source, placed[0].text
    assert band.intersects(text)  # the lower line's band reaches into the upper translation
    for order in ([upper, lower], [lower, upper]):
        rgba = paint_rgba(overlay, *order)
        both = band.intersected(text)
        box = rgba[both.top() : both.bottom() + 1, both.left() : both.right() + 1]
        assert (box[:, :, :3].min(axis=2) > 200).any()  # the letters are drawn over the band, whatever the order


def test_the_overlay_repaints_only_when_the_blocks_change(qapp: QApplication) -> None:
    window = OverlayWindow(0)
    repaints: list[int] = []
    window.update = lambda: repaints.append(1)  # type: ignore[method-assign]
    window.set_blocks([subtitle(["Yakın dur."])])
    window.set_blocks([subtitle(["Yakın dur."])])  # an unchanged frame sends an equal list
    assert len(repaints) == 1
    window.set_blocks([])
    window.set_blocks([])
    assert len(repaints) == 2
    window.deleteLater()
