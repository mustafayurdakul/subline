"""Shared OCR types and the engine interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass(slots=True)
class TextLine:
    """One recognised line of text.

    `quad` is a (4, 2) float32 array of pixel corners in frame coordinates,
    ordered top-left, top-right, bottom-right, bottom-left.
    """

    text: str
    quad: np.ndarray
    confidence: float

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """Axis-aligned (x0, y0, x1, y1) in integer pixels; x1 and y1 exclusive."""
        xs = self.quad[:, 0]
        ys = self.quad[:, 1]
        return (
            int(np.floor(xs.min())),
            int(np.floor(ys.min())),
            int(np.ceil(xs.max())),
            int(np.ceil(ys.max())),
        )

    @property
    def height(self) -> float:
        box = self.bbox
        return float(box[3] - box[1])

    def shifted(self, dx: float, dy: float) -> TextLine:
        """The same line moved by (dx, dy): maps a crop back into full-frame
        coordinates."""
        return TextLine(self.text, self.quad + np.array([dx, dy], dtype=np.float32), self.confidence)


@dataclass(slots=True)
class OcrResult:
    lines: list[TextLine]
    timings_ms: dict[str, float] = field(default_factory=dict)

    def shifted(self, dx: float, dy: float) -> OcrResult:
        return OcrResult([line.shifted(dx, dy) for line in self.lines], dict(self.timings_ms))


class OcrEngine(Protocol):
    """Detect and recognise all text in a BGR image."""

    name: str

    def recognize(self, image_bgr: np.ndarray) -> OcrResult: ...
