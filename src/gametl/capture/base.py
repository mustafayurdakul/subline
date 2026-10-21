"""Shared capture types."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Rect = tuple[int, int, int, int]
"""Screen rectangle in physical pixels: (left, top, right, bottom)."""


@dataclass(slots=True)
class Frame:
    """One captured frame of the target window.

    `image` is HxWx3 BGR uint8 (OpenCV convention). `window_rect` is where the
    captured area sits on screen, so a pixel (x, y) in the frame maps to screen
    position (left + x, top + y). It is None when unknown (e.g. a loaded image).
    """

    image: np.ndarray
    timestamp: float
    window_rect: Rect | None = None

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])
