"""Pick the background and text colours of a text box from the frame, and
judge whether a flat "patch" of the background colour would look right.

For the patch overlay style the original text is painted over with the
background colour and the translation drawn in the text colour. On a busy
background (artwork, gradients, video) no single colour hides the original,
so the caller falls back to a translucent pill with outlined text.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Box = tuple[int, int, int, int]
BGR = tuple[int, int, int]


@dataclass(slots=True)
class ColorSample:
    bg: BGR
    fg: BGR
    busy: bool  # background too varied for a flat patch
    contrast: float  # luminance difference between fg and bg, 0..255


def _luminance(pixels: np.ndarray) -> np.ndarray:
    px = pixels.astype(np.float32)
    return 0.114 * px[..., 0] + 0.587 * px[..., 1] + 0.299 * px[..., 2]


def _robust_spread(values: np.ndarray) -> float:
    """Standard deviation estimated from the median absolute deviation: a
    minority of outliers (anti-aliased glyph fringe inside the ring) does not
    register, while artwork or a steep gradient does."""
    if len(values) < 2:
        return 0.0
    median = float(np.median(values))
    return 1.4826 * float(np.median(np.abs(values - median)))


def analyze_colors(
    image_bgr: np.ndarray,
    bbox: Box,
    margin: int = 3,
    text_fraction: float = 0.2,
    busy_std: float = 28.0,
) -> ColorSample:
    """Background: the median of a `margin`-pixel ring just outside the box
    (the box is tight around the glyphs, so the ring is background). Text:
    the median of the `text_fraction` of inner pixels that differ most from
    it. Busy: the ring, or the inner pixels nearest the background colour,
    vary by more than `busy_std` in luminance."""
    h, w = image_bgr.shape[:2]
    x0, y0 = max(0, bbox[0]), max(0, bbox[1])
    x1, y1 = min(w, bbox[2]), min(h, bbox[3])
    if x1 <= x0 or y1 <= y0:
        return ColorSample((0, 0, 0), (255, 255, 255), False, 255.0)

    # The ring just outside the box is background; the inside is text plus background.
    ox0, oy0 = max(0, x0 - margin), max(0, y0 - margin)
    ox1, oy1 = min(w, x1 + margin), min(h, y1 + margin)
    outer = image_bgr[oy0:oy1, ox0:ox1]
    mask = np.ones(outer.shape[:2], dtype=bool)
    mask[y0 - oy0 : y1 - oy0, x0 - ox0 : x1 - ox0] = False
    ring = outer[mask]
    inner = image_bgr[y0:y1, x0:x1].reshape(-1, 3)
    if ring.size == 0:
        ring = inner

    # Text colour: the inner pixels that differ most from the background colour.
    bg = np.median(ring, axis=0)
    distance = np.abs(inner.astype(np.int16) - bg.astype(np.int16)).sum(axis=1)
    k = max(1, int(len(distance) * text_fraction))
    order = np.argsort(distance)
    fg = np.median(inner[order[-k:]], axis=0)

    ring_std = _robust_spread(_luminance(ring))
    # Inner pixels clearly on the background side (not glyph, not anti-aliased
    # edge): if those vary, there is artwork behind the text.
    fg_distance = float(np.abs(fg.astype(np.int16) - bg.astype(np.int16)).sum())
    near = inner[distance < 0.25 * max(fg_distance, 1.0)]
    base_std = _robust_spread(_luminance(near)) if len(near) > 20 else 0.0
    busy = ring_std > busy_std or base_std > busy_std

    contrast = abs(float(_luminance(fg[None, :])[0]) - float(_luminance(bg[None, :])[0]))
    return ColorSample(
        bg=tuple(int(v) for v in bg),  # type: ignore[arg-type]
        fg=tuple(int(v) for v in fg),  # type: ignore[arg-type]
        busy=busy,
        contrast=contrast,
    )


def bgr_to_rgb(c: BGR) -> tuple[int, int, int]:
    return (c[2], c[1], c[0])
