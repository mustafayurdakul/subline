from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gametl.overlay.selector import AreaSelector, rect_to_zone_spec  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def test_rect_to_zone_spec_fractions_and_clamping() -> None:
    area = (0, 30, 1280, 750)  # client area inside a frame with a 30 px title bar
    assert rect_to_zone_spec((0, 570, 1280, 750), area) == "0.0000,0.7500,1.0000,0.2500"
    assert rect_to_zone_spec((320, 30, 960, 390), area) == "0.2500,0.0000,0.5000,0.5000"
    # Outside the client area gets clamped to its edge.
    assert rect_to_zone_spec((-50, 0, 640, 390), area) == "0.0000,0.0000,0.5000,0.5000"


def test_drag_emits_selection_in_frame_pixels(qapp: QApplication) -> None:
    selector = AreaSelector((100, 100, 900, 700))
    got: list[tuple] = []
    selector.selected.connect(got.append)
    selector.start()
    qapp.processEvents()
    QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(50, 400))
    QTest.mouseMove(selector, QPoint(700, 560))
    QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(700, 560))
    qapp.processEvents()
    assert got == [(50, 400, 701, 561)]


def test_mirrored_selection_is_symmetric_about_the_centre(qapp: QApplication) -> None:
    selector = AreaSelector((100, 100, 900, 700), mirror_x=True, center_x=400)
    got: list[tuple] = []
    selector.selected.connect(got.append)
    selector.start()
    qapp.processEvents()
    # A rough drag on the left side only: from x=50 to x=300.
    QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(50, 400))
    QTest.mouseMove(selector, QPoint(300, 560))
    QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(300, 560))
    qapp.processEvents()
    assert got == [(50, 400, 750, 561)]  # mirrored: 400 - 350 .. 400 + 350


def test_tiny_drag_and_escape_cancel(qapp: QApplication) -> None:
    selector = AreaSelector((100, 100, 900, 700))
    cancelled: list[int] = []
    selector.cancelled.connect(lambda: cancelled.append(1))
    selector.start()
    QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(53, 52))
    qapp.processEvents()
    assert cancelled == [1]

    selector = AreaSelector((100, 100, 900, 700))
    selector.cancelled.connect(lambda: cancelled.append(2))
    selector.start()
    QTest.keyClick(selector, Qt.Key.Key_Escape)
    qapp.processEvents()
    assert cancelled == [1, 2]
