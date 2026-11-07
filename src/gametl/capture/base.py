"""Shared capture types."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class Frame:
    """One captured frame of the target window: `image` is HxWx3 BGR uint8
    (OpenCV convention)."""

    image: np.ndarray
    timestamp: float

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])
