"""Overlay window: native styles (click-through, no activation, topmost),
following the target window, and text fitting. Needs a desktop session."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from gametl.capture.windows import enable_per_monitor_dpi_awareness, window_rect  # noqa: E402
from gametl.overlay.window import (  # noqa: E402
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    OverlayWindow,
    RenderBlock,
)


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


def test_fit_font_fits_width(qapp: QApplication, target: QWidget) -> None:
    overlay = OverlayWindow(int(target.winId()))
    lines = ["A fairly long translated subtitle line", "second"]
    font = overlay.fit_font(lines, width=300, height=60)
    fm = QFontMetrics(font)
    assert max(fm.horizontalAdvance(ln) for ln in lines) <= 300
    assert font.pixelSize() >= 6
    big = overlay.fit_font(["Hi"], width=1000, height=50)
    assert big.pixelSize() == int(50 * 0.8)


def test_set_blocks_and_paint(qapp: QApplication, target: QWidget) -> None:
    overlay = OverlayWindow(int(target.winId()), hide_when_unfocused=False, exclude_from_capture=False)
    overlay.start()
    overlay.set_blocks([RenderBlock((10, 10, 200, 40), ["HELLO"], bg=(0, 0, 0), fg=(255, 255, 255))])
    qapp.processEvents()
    image = overlay.grab().toImage()
    assert image.width() > 0
    overlay.close()
