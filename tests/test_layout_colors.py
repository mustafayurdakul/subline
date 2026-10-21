from __future__ import annotations

import cv2
import numpy as np

from gametl.layout.colors import analyze_colors, bgr_to_rgb


def test_white_text_on_blue() -> None:
    blue = (200, 50, 20)  # BGR
    image = np.empty((120, 400, 3), dtype=np.uint8)
    image[:] = blue
    cv2.putText(image, "HELLO", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 4)
    ys, xs = np.where(image[:, :, 1] > 200)  # the white glyph pixels
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

    sample = analyze_colors(image, bbox)
    assert all(abs(a - b) <= 2 for a, b in zip(sample.bg, blue, strict=True)), sample.bg
    assert all(v >= 250 for v in sample.fg), sample.fg


def _text_image(background: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    image = background.copy()
    cv2.putText(image, "HELLO", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 4)
    ys, xs = np.where(np.all(image == 255, axis=2))
    return image, (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def test_flat_background_is_not_busy_and_has_contrast() -> None:
    flat = np.full((120, 400, 3), (90, 40, 20), dtype=np.uint8)
    image, bbox = _text_image(flat)
    sample = analyze_colors(image, bbox)
    assert sample.busy is False
    assert sample.contrast > 150
    assert sample.fg == (255, 255, 255)


def test_noisy_background_is_busy() -> None:
    rng = np.random.default_rng(1)
    noisy = rng.integers(0, 200, size=(120, 400, 3), dtype=np.uint8)
    image, bbox = _text_image(noisy)
    assert analyze_colors(image, bbox).busy is True


def test_gradient_background_is_busy_only_when_steep() -> None:
    gentle = np.zeros((120, 400, 3), dtype=np.uint8)
    gentle[:] = np.linspace(40, 60, 400, dtype=np.uint8)[None, :, None]
    image, bbox = _text_image(gentle)
    assert analyze_colors(image, bbox).busy is False
    steep = np.zeros((120, 400, 3), dtype=np.uint8)
    steep[:] = np.linspace(0, 250, 400, dtype=np.uint8)[None, :, None]
    image, bbox = _text_image(steep)
    assert analyze_colors(image, bbox).busy is True


def test_degenerate_box_gets_defaults() -> None:
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    sample = analyze_colors(image, (5, 5, 5, 5))
    assert (sample.bg, sample.fg, sample.busy) == ((0, 0, 0), (255, 255, 255), False)


def test_bgr_to_rgb() -> None:
    assert bgr_to_rgb((1, 2, 3)) == (3, 2, 1)
