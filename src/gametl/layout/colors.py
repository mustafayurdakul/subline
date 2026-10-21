"""Pick the background and text colours of a text box from the frame, for
the "patch" overlay style: paint the background colour over the original
text, draw the translation in the text colour."""

from __future__ import annotations

import numpy as np

Box = tuple[int, int, int, int]
BGR = tuple[int, int, int]


def sample_colors(image_bgr: np.ndarray, bbox: Box, margin: int = 3, text_fraction: float = 0.2) -> tuple[BGR, BGR]:
    """Returns (background, text) as BGR tuples.

    Background: median colour of a `margin`-pixel ring just outside the box
    (the box is tight around the glyphs, so the ring is pure background).
    Text: median of the `text_fraction` of pixels inside the box that differ
    most from the background.
    """
    h, w = image_bgr.shape[:2]
    x0, y0 = max(0, bbox[0]), max(0, bbox[1])
    x1, y1 = min(w, bbox[2]), min(h, bbox[3])
    if x1 <= x0 or y1 <= y0:
        return (0, 0, 0), (255, 255, 255)

    ox0, oy0 = max(0, x0 - margin), max(0, y0 - margin)
    ox1, oy1 = min(w, x1 + margin), min(h, y1 + margin)
    outer = image_bgr[oy0:oy1, ox0:ox1]
    mask = np.ones(outer.shape[:2], dtype=bool)
    mask[y0 - oy0 : y1 - oy0, x0 - ox0 : x1 - ox0] = False
    ring = outer[mask]
    inner = image_bgr[y0:y1, x0:x1].reshape(-1, 3)
    if ring.size == 0:
        ring = inner

    bg = np.median(ring, axis=0)
    distance = np.abs(inner.astype(np.int16) - bg.astype(np.int16)).sum(axis=1)
    k = max(1, int(len(distance) * text_fraction))
    top = np.argpartition(distance, -k)[-k:]
    fg = np.median(inner[top], axis=0)
    return tuple(int(v) for v in bg), tuple(int(v) for v in fg)


def bgr_to_rgb(c: BGR) -> tuple[int, int, int]:
    return (c[2], c[1], c[0])
