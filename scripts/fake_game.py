"""A stand-in for a game window, for testing capture, OCR and the overlay
without a real game: dark animated background, a HUD line, and a large
subtitle at the bottom that changes every few seconds.

  python scripts/fake_game.py                 # 1280x720, new line every 2.5 s
  python scripts/fake_game.py --typewriter    # reveal each line character by character
  python scripts/fake_game.py --interval 4 --width 1920 --height 1080

Capture it with:  python scripts/spike_capture_ocr.py --window "Fake Game"
"""

from __future__ import annotations

import argparse
import math
import sys
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QWidget

LINES = [
    "Where were you when the lights went out?",
    "I told you not to open that door.",
    "We leave at dawn. Pack only what you can carry.",
    "The bridge is gone. We need another way across.",
    "Stay close, and keep your voice down.",
]


class FakeGame(QWidget):
    def __init__(self, interval: float, typewriter: bool, chars_per_second: float, busy: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("Fake Game")
        self.interval = interval
        self.typewriter = typewriter
        self.cps = chars_per_second
        self.busy = busy
        self.start = time.perf_counter()
        timer = QTimer(self)
        timer.timeout.connect(self.update)
        timer.start(33)

    def current_line(self) -> str:
        elapsed = time.perf_counter() - self.start
        index = int(elapsed // self.interval) % len(LINES)
        line = LINES[index]
        if self.typewriter:
            shown = int((elapsed % self.interval) * self.cps)
            line = line[:shown]
        return line

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = time.perf_counter() - self.start

        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0, QColor(30, 40, 70))
        gradient.setColorAt(1, QColor(10, 10, 20))
        p.fillRect(self.rect(), gradient)

        if self.busy:
            # A static mosaic behind the subtitle band: artwork a flat patch cannot hide.
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(0, w, 48):
                for j in range(int(h * 0.74), h, 28):
                    seed = (i * 7919 + j * 104729) % 997
                    p.setBrush(QColor(40 + seed % 160, 60 + (seed * 3) % 140, 80 + (seed * 7) % 120))
                    p.drawRect(i, j, 48, 28)

        # Something that moves, so frames are never identical.
        cx = w * (0.5 + 0.4 * math.sin(t * 0.7))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(200, 160, 60))
        p.drawEllipse(QRectF(cx - 40, h * 0.3 - 40, 80, 80))

        # HUD
        p.setPen(QColor(230, 230, 230))
        p.setFont(QFont("Segoe UI", 14))
        p.drawText(20, 34, f"HP 87/100   Ammo 24   {int(t)}s")

        # Subtitle with a drop shadow
        font = QFont("Segoe UI", 26)
        font.setBold(True)
        p.setFont(font)
        rect = QRectF(0, h * 0.78, w, h * 0.15)
        line = self.current_line()
        p.setPen(QColor(0, 0, 0, 200))
        p.drawText(rect.translated(2, 2), Qt.AlignmentFlag.AlignCenter, line)
        p.setPen(QColor(255, 255, 255))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, line)
        p.end()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", type=float, default=2.5, help="seconds per subtitle line")
    parser.add_argument("--typewriter", action="store_true", help="reveal lines character by character")
    parser.add_argument("--cps", type=float, default=25.0, help="characters per second in typewriter mode")
    parser.add_argument("--busy", action="store_true", help="draw a mosaic behind the subtitle band")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    game = FakeGame(args.interval, args.typewriter, args.cps, args.busy)
    game.resize(args.width, args.height)
    game.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
