"""Overlay window: native styles (click-through, no activation, topmost),
following the target window, and text fitting. Needs a desktop session."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtWidgets import QApplication, QWidget

from gametl.capture.windows import enable_per_monitor_dpi_awareness, find_window, list_windows, window_rect
from gametl.overlay.paint import RenderBlock, source_font_px, subtitle_rect
from gametl.overlay.window import (
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    OverlayWindow,
)


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


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    enable_per_monitor_dpi_awareness()
    app = QApplication.instance() or QApplication([])
    return app  # type: ignore[return-value]


@pytest.fixture
def target(qapp: QApplication) -> QWidget:
    w = QWidget()
    w.setWindowTitle("gametl test target")
    w.resize(400, 300)
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    qapp.processEvents()


def test_overlay_native_styles_and_following(qapp: QApplication, target: QWidget) -> None:
    hwnd = int(target.winId())
    overlay = OverlayWindow(hwnd, hide_when_unfocused=False, exclude_from_capture=True)
    overlay.start()
    qapp.processEvents()
    try:
        ex = overlay.ex_style()
        for flag, name in (
            (WS_EX_TRANSPARENT, "WS_EX_TRANSPARENT"),
            (WS_EX_LAYERED, "WS_EX_LAYERED"),
            (WS_EX_NOACTIVATE, "WS_EX_NOACTIVATE"),
            (WS_EX_TOOLWINDOW, "WS_EX_TOOLWINDOW"),
            (WS_EX_TOPMOST, "WS_EX_TOPMOST"),
        ):
            assert ex & flag, f"missing {name} in 0x{ex:08X}"

        rect = window_rect(hwnd)
        g = overlay.geometry()
        assert (g.x(), g.y(), g.x() + g.width(), g.y() + g.height()) == rect

        target.move(target.x() + 60, target.y() + 25)
        qapp.processEvents()
        overlay._follow()
        rect2 = window_rect(hwnd)
        g2 = overlay.geometry()
        assert rect2 != rect
        assert (g2.x(), g2.y(), g2.x() + g2.width(), g2.y() + g2.height()) == rect2
    finally:
        overlay.close()
        qapp.processEvents()


def test_own_windows_are_not_listed_as_capture_targets(qapp: QApplication, target: QWidget) -> None:
    """A typed title must never match gametl's own settings window."""
    assert "gametl test target" not in [w.title for w in list_windows()]
    assert "gametl test target" in [w.title for w in list_windows(include_own=True)]
    assert find_window("gametl test target") is None


def test_in_place_layout_fits_the_width(qapp: QApplication, target: QWidget) -> None:
    overlay = OverlayWindow(int(target.winId())).painter
    block = RenderBlock((0, 0, 300, 60), ["A fairly long translated subtitle line", "second"], source_lines=2)
    layout = overlay.layout_for(block)
    assert all(overlay.measurer("regular")(line, layout.font_px) <= 300 for line in layout.lines)
    assert layout.font_px >= 6
    assert overlay.layout_for(block) is layout  # cached
    short = overlay.layout_for(RenderBlock((0, 0, 1000, 50), ["Hi"]))
    assert short.font_px == source_font_px(50, 1) == int(50 * 0.8)


def test_set_blocks_and_paint_all_styles(qapp: QApplication, target: QWidget) -> None:
    overlay = OverlayWindow(int(target.winId()), hide_when_unfocused=False, exclude_from_capture=False)
    overlay.start()
    long_text = "a translation that is much longer than the source text was and must wrap"
    overlay.set_blocks(
        [
            RenderBlock((10, 10, 200, 40), ["HELLO"], bg=(0, 0, 0), fg=(255, 255, 255)),
            RenderBlock((10, 60, 200, 90), [long_text], style="pill", room_below=80),
            RenderBlock((10, 200, 200, 230), ["outlined"], style="outline"),
            RenderBlock((60, 260, 160, 280), [long_text], style="subtitle", zone=(0, 240, 400, 300), font_px=18),
            # One word: the wrapper never measures, so the font must still get registered (crashed before).
            RenderBlock((60, 260, 160, 280), ["Run!"], style="subtitle", zone=(0, 240, 400, 300), font_px=24),
            RenderBlock(
                (60, 260, 160, 280), ["Yes."], style="subtitle", zone=(0, 240, 400, 300), font_px=24, position="bottom"
            ),
        ]
    )
    overlay.grab()
    assert overlay.paint_errors == 0
    qapp.processEvents()
    image = overlay.grab().toImage()
    assert image.width() > 0
    layout = overlay.painter.layout_for(overlay._blocks[1])
    assert len(layout.lines) > 1 and layout.grown is True
    overlay.close()
