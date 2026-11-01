"""Drag-to-select an area of the game window.

A dimmed layer over the window. Drag a rectangle; it stays on screen to be
adjusted (arrow keys nudge it, Ctrl+arrows resize it, a new drag replaces
it) until Enter confirms or Escape cancels. The result is reported in frame
pixels (relative to the window's top-left); the caller stores it as
fractions of the client area so it survives window moves and resizes.

Subtitles are centred, so a selection can be kept symmetric about the
window's (or the client area's) horizontal centre: then one edge and the
height are enough. Holding Shift while dragging inverts that default, so a
left-hand label can be selected freely in a profile that centres, and a
centred strip can be drawn in one that does not.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..geometry import Box

MIN_SIZE = 8  # px; smaller drags count as a cancel
NUDGE = 1  # px per arrow key
BIG_NUDGE = 10  # px per arrow key with Shift
DIM_COLOR = QColor(0, 0, 0, 110)
ACCENT_COLOR = QColor(80, 220, 120)
WHITE = QColor(255, 255, 255)

_ARROWS = {
    Qt.Key.Key_Left: (-1, 0),
    Qt.Key.Key_Right: (1, 0),
    Qt.Key.Key_Up: (0, -1),
    Qt.Key.Key_Down: (0, 1),
}


def rect_to_zone_spec(rect: Box, area: Box, decimals: int = 4) -> str:
    """Frame-pixel rectangle -> 'x,y,w,h' as fractions of `area`, clamped to it."""
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
        # mirror_x: keep the selection symmetric about center_x by default; Shift inverts it for one drag.
        self.mirror_x = mirror_x
        self.center_x = center_x if center_x is not None else (x1 - x0) // 2
        self._shift = False
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._rect: QRect | None = None  # a finished drag, awaiting Enter
        self._done = False

    def start(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # -- state -------------------------------------------------------------------

    def hint(self) -> str:
        if self._rect is not None:
            return (
                f"Enter confirms. Arrow keys nudge (Shift: {BIG_NUDGE} px, Ctrl: resize). "
                "Drag again to redo. Esc cancels."
            )
        shift = "frees it" if self.mirror_x else "keeps it centred"
        return f"Drag to select the area to translate. Shift while dragging {shift}. Esc cancels."

    def mirrored(self) -> bool:
        return self.mirror_x != self._shift

    def selection(self) -> QRect | None:
        """The rectangle being dragged, or the finished one awaiting Enter."""
        if self._rect is not None:
            return QRect(self._rect)
        if self._origin is None or self._current is None:
            return None
        rect = QRect(self._origin, self._current).normalized()
        # Mirrored: the far edge sits as far from the centre line as the near one.
        if self.mirrored():
            half = max(abs(rect.left() - self.center_x), abs(rect.right() + 1 - self.center_x))
            rect = QRect(self.center_x - half, rect.top(), 2 * half, rect.height())
        return rect

    # -- events ----------------------------------------------------------------

    def _track(self, event) -> None:
        """The pointer and the Shift state, as of this mouse event."""
        self._shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._current = event.position().toPoint()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._rect = None  # a new drag replaces a finished selection
            self._track(event)
            self._origin = self._current
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._origin is not None:
            self._track(event)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        self._track(event)
        rect = self.selection()
        self._origin = self._current = None
        if rect is None or rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            self._finish(None)
            return
        self._rect = rect
        self.update()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._finish(None)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._rect is not None:
                self._finish(self._rect)
        elif key in _ARROWS and self._rect is not None:
            dx, dy = _ARROWS[key]
            step = BIG_NUDGE if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else NUDGE
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                # Resize: the right and bottom edges move, the top-left corner stays.
                self._rect.setWidth(max(MIN_SIZE, self._rect.width() + dx * step))
                self._rect.setHeight(max(MIN_SIZE, self._rect.height() + dy * step))
            else:
                self._rect.translate(dx * step, dy * step)
            self.update()
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

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), DIM_COLOR)
        if self.mirrored() and (self._origin is not None or self._rect is None):
            guide = QColor(ACCENT_COLOR)
            guide.setAlpha(160)
            p.setPen(QPen(guide, 1, Qt.PenStyle.DashLine))
            p.drawLine(self.center_x, 0, self.center_x, self.height())
        selection = self.selection()
        if selection is not None and not selection.isEmpty():
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(selection, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(ACCENT_COLOR, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(selection)
            p.setFont(QFont("Segoe UI", 10))
            p.setPen(WHITE)
            p.drawText(selection.left(), max(14, selection.top() - 6), f"{selection.width()} x {selection.height()} px")
        p.setFont(QFont("Segoe UI", 14))
        p.setPen(WHITE)
        hint_area = self.rect().adjusted(0, 24, 0, 0)
        p.drawText(hint_area, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.hint())
        p.end()
