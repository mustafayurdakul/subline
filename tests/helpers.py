"""Builders and waits shared by the tests."""

from __future__ import annotations

import time
from collections.abc import Callable
from types import SimpleNamespace

import numpy as np

from gametl.ocr.base import TextLine


def line(text: str, x0: int, y0: int, x1: int, y1: int, confidence: float = 0.95) -> TextLine:
    """An OCR line with an axis-aligned quad."""
    quad = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)
    return TextLine(text, quad, confidence)


def wait_until(predicate: Callable[[], bool], timeout: float = 5.0, tick: Callable[[], None] | None = None) -> bool:
    """Poll `predicate` until it holds or `timeout` passes, running `tick`
    (an event loop's processEvents, say) between polls."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if tick is not None:
            tick()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def text_response(body: str, stop_reason: str = "end_turn", usage: SimpleNamespace | None = None) -> SimpleNamespace:
    """A Messages API reply whose one text block is `body`, as the stub clients return it."""
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        content=[SimpleNamespace(type="text", text=body)],
        usage=usage if usage is not None else SimpleNamespace(input_tokens=1, output_tokens=1),
    )
