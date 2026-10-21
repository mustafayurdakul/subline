from __future__ import annotations

import cv2
import numpy as np

from gametl.layout.colors import bgr_to_rgb, sample_colors


def test_sample_colors_white_text_on_blue() -> None:
    blue = (200, 50, 20)  # BGR
    image = np.empty((120, 400, 3), dtype=np.uint8)
    image[:] = blue
    cv2.putText(image, "HELLO", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 4)
    ys, xs = np.where(image[:, :, 1] > 200)  # the white glyph pixels
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

    bg, fg = sample_colors(image, bbox)
    assert all(abs(a - b) <= 2 for a, b in zip(bg, blue)), bg
    assert all(v >= 250 for v in fg), fg


def test_sample_colors_degenerate_box() -> None:
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    assert sample_colors(image, (5, 5, 5, 5)) == ((0, 0, 0), (255, 255, 255))


def test_bgr_to_rgb() -> None:
    assert bgr_to_rgb((1, 2, 3)) == (3, 2, 1)
