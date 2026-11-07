from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gametl.overlay.selector import AreaSelector, rect_to_zone_spec

SHIFT = Qt.KeyboardModifier.ShiftModifier
CTRL = Qt.KeyboardModifier.ControlModifier
NONE = Qt.KeyboardModifier.NoModifier


def drag(selector: AreaSelector, start: QPoint, end: QPoint, modifier=NONE) -> None:
    QTest.mousePress(selector, Qt.MouseButton.LeftButton, modifier, start)
    QTest.mouseMove(selector, end)
    QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, modifier, end)


def started(qapp: QApplication, **kwargs) -> tuple[AreaSelector, list[tuple], list[int]]:
    selector = AreaSelector((100, 100, 900, 700), **kwargs)
    got: list[tuple] = []
    cancelled: list[int] = []
    selector.selected.connect(got.append)
    selector.cancelled.connect(lambda: cancelled.append(1))
    selector.start()
    qapp.processEvents()
    return selector, got, cancelled


def test_rect_to_zone_spec_fractions_and_clamping() -> None:
    area = (0, 30, 1280, 750)  # client area inside a frame with a 30 px title bar
    assert rect_to_zone_spec((0, 570, 1280, 750), area) == "0.0000,0.7500,1.0000,0.2500"
    assert rect_to_zone_spec((320, 30, 960, 390), area) == "0.2500,0.0000,0.5000,0.5000"
    # Outside the client area gets clamped to its edge.
    assert rect_to_zone_spec((-50, 0, 640, 390), area) == "0.0000,0.0000,0.5000,0.5000"


def test_a_selection_with_nothing_inside_the_client_area_gives_no_spec() -> None:
    client = (8, 31, 1288, 751)  # a windowed game: title bar above, borders round it
    assert rect_to_zone_spec((200, 4, 900, 28), client) is None  # all on the title bar
    assert rect_to_zone_spec((1288, 100, 1296, 700), client) is None  # all on the right border
    assert rect_to_zone_spec((200, 4, 900, 32), client) == "0.1500,0.0000,0.5469,0.0014"  # one row inside


def test_drag_then_enter_emits_selection_in_frame_pixels(qapp: QApplication) -> None:
    selector, got, _ = started(qapp)
    drag(selector, QPoint(50, 400), QPoint(700, 560))
    qapp.processEvents()
    assert got == []  # the drag is finished but waits for Enter
    assert selector.selection() is not None and "Enter confirms" in selector.hint()
    QTest.keyClick(selector, Qt.Key.Key_Return)
    assert got == [(50, 400, 701, 561)]


def test_free_by_default_shift_mirrors(qapp: QApplication) -> None:
    selector, got, _ = started(qapp, center_x=400)
    assert "keeps it centred" in selector.hint()
    drag(selector, QPoint(50, 400), QPoint(300, 560))
    QTest.keyClick(selector, Qt.Key.Key_Return)
    assert got == [(50, 400, 301, 561)]  # free: exactly what was dragged

    selector, got, _ = started(qapp, center_x=400)
    drag(selector, QPoint(50, 400), QPoint(300, 560), SHIFT)
    QTest.keyClick(selector, Qt.Key.Key_Return)
    assert got == [(50, 400, 750, 561)]  # mirrored: 400 - 350 .. 400 + 350


def test_centred_profile_mirrors_by_default_and_shift_frees(qapp: QApplication) -> None:
    selector, got, _ = started(qapp, mirror_x=True, center_x=400)
    assert "frees it" in selector.hint()
    drag(selector, QPoint(50, 400), QPoint(300, 560))
    QTest.keyClick(selector, Qt.Key.Key_Return)
    assert got == [(50, 400, 750, 561)]

    selector, got, _ = started(qapp, mirror_x=True, center_x=400)
    drag(selector, QPoint(50, 400), QPoint(300, 560), SHIFT)
    QTest.keyClick(selector, Qt.Key.Key_Return)
    assert got == [(50, 400, 301, 561)]  # a left-hand label can be selected on its own


def test_arrow_keys_adjust_before_enter(qapp: QApplication) -> None:
    selector, got, _ = started(qapp)
    drag(selector, QPoint(50, 400), QPoint(300, 560))
    QTest.keyClick(selector, Qt.Key.Key_Left)  # 1 px
    QTest.keyClick(selector, Qt.Key.Key_Down, SHIFT)  # 10 px
    QTest.keyClick(selector, Qt.Key.Key_Right, CTRL)  # wider by 1 px, left edge stays
    QTest.keyClick(selector, Qt.Key.Key_Up, CTRL | SHIFT)  # 10 px shorter
    QTest.keyClick(selector, Qt.Key.Key_Return)
    assert got == [(49, 410, 301, 561)]


def test_a_new_drag_replaces_the_finished_one(qapp: QApplication) -> None:
    selector, got, _ = started(qapp)
    drag(selector, QPoint(50, 400), QPoint(300, 560))
    drag(selector, QPoint(100, 100), QPoint(200, 150))
    QTest.keyClick(selector, Qt.Key.Key_Return)
    assert got == [(100, 100, 201, 151)]


def test_tiny_drag_and_escape_cancel(qapp: QApplication) -> None:
    selector, got, cancelled = started(qapp)
    drag(selector, QPoint(50, 50), QPoint(53, 52))
    qapp.processEvents()
    assert cancelled == [1] and got == []

    selector, got, cancelled = started(qapp)
    QTest.keyClick(selector, Qt.Key.Key_Escape)
    assert cancelled == [1]

    selector, got, cancelled = started(qapp)
    drag(selector, QPoint(50, 400), QPoint(300, 560))
    QTest.keyClick(selector, Qt.Key.Key_Escape)  # after a drag too
    assert cancelled == [1] and got == []
