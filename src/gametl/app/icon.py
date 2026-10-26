"""The app's mark, drawn in code so the app needs no image assets: a window
frame with the subtitle strip along its bottom. The tray icon says the
overlay's state with it: grey when idle, gold when running, a gold frame
with a grey strip when paused, a gold frame alone while starting."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

GOLD = QColor("#A98E5C")
GREY = QColor("#8E8E97")
DARK = QColor("#131316")


def make_icon(running: bool, paused: bool = False, starting: bool = False, size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    unit = size / 64
    frame = GOLD if running or starting or paused else GREY
    strip = GOLD if running and not paused else GREY
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(DARK)
    p.drawRect(QRectF(2 * unit, 2 * unit, 60 * unit, 60 * unit))
    pen = QPen(frame)
    pen.setWidthF(5 * unit)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(10.5 * unit, 10.5 * unit, 43 * unit, 43 * unit))
    if not starting:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(strip)
        p.drawRect(QRectF(21 * unit, 40 * unit, 22 * unit, 6 * unit))
    p.end()
    return QIcon(pixmap)
