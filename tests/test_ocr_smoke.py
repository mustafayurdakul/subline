"""Smoke test: the OCR engine reads a line of rendered text and returns a box
that lies inside the image. First run downloads the PP-OCR models."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from gametl.ocr.rapid import RapidOcrEngine

WIDTH, HEIGHT = 900, 160


def render_line(text: str) -> np.ndarray:
    """White text on a dark background, like a typical subtitle. Returns BGR."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (20, 20, 30))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except OSError:
        font = ImageFont.load_default(size=48)
    draw.text((30, 50), text, fill=(240, 240, 240), font=font)
    return np.asarray(img)[:, :, ::-1].copy()


@pytest.fixture(scope="module")
def engine() -> RapidOcrEngine:
    return RapidOcrEngine(lang="en")


def test_reads_rendered_english_line(engine: RapidOcrEngine) -> None:
    result = engine.recognize(render_line("The quick brown fox jumps over"))
    joined = " ".join(line.text for line in result.lines).lower()
    assert "quick" in joined and "fox" in joined, result.lines

    x0, y0, x1, y1 = result.lines[0].bbox
    assert 0 <= x0 < x1 <= WIDTH
    assert 0 <= y0 < y1 <= HEIGHT
    assert result.timings_ms["total"] > 0


def test_shift_moves_boxes(engine: RapidOcrEngine) -> None:
    result = engine.recognize(render_line("Hello world"))
    moved = result.shifted(100, 50)
    assert len(moved.lines) == len(result.lines)
    for a, b in zip(result.lines, moved.lines, strict=True):
        assert b.bbox[0] == a.bbox[0] + 100
        assert b.bbox[1] == a.bbox[1] + 50
        assert b.text == a.text


def test_blank_image_has_no_lines(engine: RapidOcrEngine) -> None:
    blank = np.full((HEIGHT, WIDTH, 3), 30, dtype=np.uint8)
    result = engine.recognize(blank)
    assert result.lines == []
