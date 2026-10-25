"""The pipeline thread's per-frame work with a fake OCR engine: which region
is read, the full-scan cadence, the frame diff, and translations reaching
the render blocks. No capture, no window, no real OCR."""

from __future__ import annotations

import os
import time

import numpy as np

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gametl.app.pipeline import PipelineConfig, PipelineThread
from gametl.capture.base import Frame
from gametl.ocr.base import OcrResult, TextLine
from gametl.translate.cache import TranslationCache
from gametl.translate.dummy import UppercaseTranslator
from gametl.translate.service import TranslationService

WIDTH, HEIGHT = 1000, 720
STRIP = (0, 600, WIDTH, 700)


def line(text: str, x0: int, y0: int, x1: int, y1: int) -> TextLine:
    quad = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)
    return TextLine(text, quad, 0.95)


class FakeEngine:
    """Answers every call with the same lines (in crop coordinates) and
    records the shape of each image it was given."""

    name = "fake"

    def __init__(self, lines: list[TextLine] | None = None) -> None:
        self.lines = lines or []
        self.shapes: list[tuple[int, ...]] = []

    def recognize(self, image_bgr: np.ndarray) -> OcrResult:
        self.shapes.append(image_bgr.shape)
        return OcrResult(lines=list(self.lines))


def frame(value: int = 20) -> Frame:
    return Frame(image=np.full((HEIGHT, WIDTH, 3), value, dtype=np.uint8), timestamp=time.perf_counter())


def pipeline(engine: FakeEngine, **config) -> PipelineThread:
    service = TranslationService(UppercaseTranslator(), TranslationCache(), target_lang="tr", source_lang="en")
    return PipelineThread(0, engine, service, PipelineConfig(**config))


def process_until(thread: PipelineThread, predicate, frames: int = 50):
    """Feed identical frames until `predicate(render)` holds; the translation
    arrives from the worker thread, so a few frames may pass first."""
    render = []
    for _ in range(frames):
        render = thread._process(frame())
        if predicate(render):
            return render
        time.sleep(0.02)
    raise AssertionError(f"condition not met after {frames} frames; last render {render}")


def test_roi_reads_only_the_strip_and_shifts_lines_back() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, diff_threshold=0)
    blocks, lines = thread.track_frame(frame())
    assert engine.shapes == [(100, WIDTH, 3)]  # the strip, not the frame
    assert [ln.bbox for ln in lines] == [(300, 620, 700, 660)]  # back in frame coordinates
    assert [b.bbox for b in blocks] == [(300, 620, 700, 660)]


def test_full_scan_cadence_including_every_frame() -> None:
    engine = FakeEngine()
    thread = pipeline(engine, roi=STRIP, full_scan_every=3, diff_threshold=0)
    for _ in range(6):
        thread.track_frame(frame())
    # frames 1 and 4 sweep the whole area as well as the strip
    assert [len(s) == 3 and s[0] for s in engine.shapes] == [100, HEIGHT, 100, 100, 100, HEIGHT, 100, 100]

    engine = FakeEngine()
    thread = pipeline(engine, roi=STRIP, full_scan_every=1, diff_threshold=0)
    for _ in range(3):
        thread.track_frame(frame())
    assert [s[0] for s in engine.shapes] == [100, HEIGHT] * 3  # every frame, not never


def test_translation_reaches_the_render_blocks() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="subtitle", diff_threshold=0)
    try:
        render = process_until(thread, lambda r: bool(r))
        (block,) = render
        assert block.lines == ["STAY CLOSE."]
        assert block.style == "subtitle" and block.zone == STRIP
        assert block.bbox == (300, 620, 700, 660)
    finally:
        thread.service.shutdown()


def test_unchanged_frames_skip_ocr_until_something_moves() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, max_skipped=100)
    try:
        process_until(thread, lambda r: bool(r))  # read, confirmed, translated
        reads, skipped = len(engine.shapes), thread.skipped
        assert reads >= 2  # the block needed a second sighting before it was stable
        for _ in range(5):
            render = thread._process(frame())
            assert render and render[0].lines == ["STAY CLOSE."]  # still drawn while skipping
        assert len(engine.shapes) == reads  # no OCR on identical frames
        assert thread.skipped == skipped + 5

        changed = frame()
        changed.image[610:690, 200:800] = 255  # the strip changes: read again
        thread._process(changed)
        assert len(engine.shapes) == reads + 1
    finally:
        thread.service.shutdown()


def test_skipping_stops_after_max_skipped_and_never_while_blocks_are_unsettled() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, max_skipped=2)
    try:
        process_until(thread, lambda r: bool(r))
        reads = len(engine.shapes)
        for _ in range(3):
            thread._process(frame())
        assert len(engine.shapes) == reads + 1  # two skips, then a forced read
    finally:
        thread.service.shutdown()

    # A block waiting for confirmation is never skipped past, even on an identical frame.
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, stable_frames=3)
    try:
        for _ in range(4):
            thread._process(frame())
        assert len(engine.shapes) == 4  # stable_frames not reached: OCR every frame
        assert thread.skipped == 0
    finally:
        thread.service.shutdown()


def test_diff_disabled_reads_every_frame() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, diff_threshold=0)
    try:
        for _ in range(4):
            thread._process(frame())
        assert len(engine.shapes) == 4 and thread.skipped == 0
    finally:
        thread.service.shutdown()


def test_rescan_forgets_blocks_and_the_last_thumbnail() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP)
    try:
        process_until(thread, lambda r: bool(r))
        skipped = thread.skipped
        thread._process(frame())
        assert thread.skipped == skipped + 1
        thread._forget_blocks(reset_style=True)
        assert thread._tracker.blocks == []
        reads = len(engine.shapes)
        thread._process(frame())
        assert len(engine.shapes) == reads + 1  # read afresh after the reset
    finally:
        thread.service.shutdown()
