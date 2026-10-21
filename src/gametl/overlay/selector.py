"""Drag-to-select an area of the game window.

A dimmed layer over the window; the user drags a rectangle, which is
reported in frame pixels (relative to the window's top-left), or presses
Escape to cancel. The selection is then stored as fractions of the client
area so it survives window moves and resizes.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

Box = tuple[int, int, int, int]

MIN_SIZE = 8  # px; smaller drags count as a cancel


def rect_to_zone_spec(rect: Box, area: Box, decimals: int = 4) -> str:
    """Frame-pixel rectangle -> 'x,y,w,h' as fractions of `area`, clamped."""
    ax0, ay0, ax1, ay1 = area
    aw, ah = max(1, ax1 - ax0), max(1, ay1 - ay0)
    x0 = min(max(rect[0], ax0), ax1)
    y0 = min(max(rect[1], ay0), ay1)
    x1 = min(max(rect[2], ax0), ax1)
    y1 = min(max(rect[3], ay0), ay1)
    fx, fy = (x0 - ax0) / aw, (y0 - ay0) / ah
    fw, fh = (x1 - x0) / aw, (y1 - y0) / ah
    return ",".join(f"{v:.{decimals}f}" for v in (fx, fy, fw, fh))


class AreaSelector(QWidget):
    selected = Signal(tuple)  # (x0, y0, x1, y1) in frame pixels
    cancelled = Signal()

    def __init__(
        self,
        target_rect: Box,
        hint: str = "Drag to select the area to translate. Esc cancels.",
        mirror_x: bool = False,
        center_x: int | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        x0, y0, x1, y1 = target_rect
        self.setGeometry(x0, y0, x1 - x0, y1 - y0)
        self.hint = hint
        # Subtitles are centred: keep the selection symmetric about the window's
        # (or the client area's) horizontal centre, so one edge and the height suffice.
        self.mirror_x = mirror_x
        self.center_x = center_x if center_x is not None else (x1 - x0) // 2
        if mirror_x:
            self.hint += " The area is kept centred."
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._done = False

    def start(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # -- geometry --------------------------------------------------------------

    def selection(self) -> QRect | None:
        if self._origin is None or self._current is None:
            return None
        rect = QRect(self._origin, self._current).normalized()
        if self.mirror_x:
            half = max(abs(rect.left() - self.center_x), abs(rect.right() + 1 - self.center_x))
            rect = QRect(self.center_x - half, rect.top(), 2 * half, rect.height())
        return rect

    # -- events ----------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        self._current = event.position().toPoint()
        rect = self.selection()
        self._finish(rect if rect and rect.width() >= MIN_SIZE and rect.height() >= MIN_SIZE else None)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._finish(None)
        else:
            super().keyPressEvent(event)

    def _finish(self, rect: QRect | None) -> None:
        if self._done:
            return
        self._done = True
        if rect is None:
            self.cancelled.emit()
        else:
            self.selected.emit((rect.left(), rect.top(), rect.right() + 1, rect.bottom() + 1))
        self.close()

    # -- painting ----------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self.mirror_x:
            p.setPen(QPen(QColor(80, 220, 120, 160), 1, Qt.PenStyle.DashLine))
            p.drawLine(self.center_x, 0, self.center_x, self.height())
        sel = self.selection()
        if sel is not None and not sel.isEmpty():
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(sel, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(80, 220, 120), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel)
            p.setFont(QFont("Segoe UI", 10))
            p.setPen(QColor(255, 255, 255))
            p.drawText(sel.left(), max(14, sel.top() - 6), f"{sel.width()} x {sel.height()}")
        p.setFont(QFont("Segoe UI", 14))
        p.setPen(QColor(255, 255, 255))
        p.drawText(self.rect().adjusted(0, 24, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.hint)
        p.end()
