"""The pipeline thread's per-frame work with a fake OCR engine: which region
is read, the full-scan cadence, the frame-change gate, settings changed on
the fly, and translations reaching the render blocks. No capture, no
window, no real OCR."""

from __future__ import annotations

import os
import time
from dataclasses import replace

import numpy as np

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gametl.app.pipeline import PipelineConfig, PipelineThread
from gametl.capture.base import Frame
from gametl.ocr.base import OcrResult, TextLine
from gametl.translate.cache import TranslationCache
from gametl.translate.dummy import UppercaseTranslator
from gametl.translate.service import TranslationService
from tests.helpers import line

WIDTH, HEIGHT = 1000, 720
STRIP = (0, 600, WIDTH, 700)


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
    thread = pipeline(engine, roi=STRIP, change_threshold=0)
    blocks, lines = thread.track_frame(frame())
    assert engine.shapes == [(100, WIDTH, 3)]  # the strip, not the frame
    assert [ln.bbox for ln in lines] == [(300, 620, 700, 660)]  # back in frame coordinates
    assert [b.bbox for b in blocks] == [(300, 620, 700, 660)]


def test_full_scan_cadence_including_every_frame() -> None:
    engine = FakeEngine()
    thread = pipeline(engine, roi=STRIP, full_scan_every=3, change_threshold=0)
    for _ in range(6):
        thread.track_frame(frame())
    # frames 1 and 4 sweep the whole area as well as the strip
    assert [len(s) == 3 and s[0] for s in engine.shapes] == [100, HEIGHT, 100, 100, 100, HEIGHT, 100, 100]

    engine = FakeEngine()
    thread = pipeline(engine, roi=STRIP, full_scan_every=1, change_threshold=0)
    for _ in range(3):
        thread.track_frame(frame())
    assert [s[0] for s in engine.shapes] == [100, HEIGHT] * 3  # every frame, not never


def test_translation_reaches_the_render_blocks() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0)
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


def test_a_short_word_appearing_in_a_wide_strip_wakes_ocr() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, max_skipped=100)
    try:
        process_until(thread, lambda r: bool(r))
        thread._process(frame())
        reads = len(engine.shapes)
        small = frame()
        small.image[640:652, 480:520] = 255  # a 40 x 12 px word in a 1000 x 100 px strip
        thread._process(small)
        assert len(engine.shapes) == reads + 1  # the strip's mean barely moved; the local change is plain
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
    thread = pipeline(engine, roi=STRIP, change_threshold=0)
    try:
        for _ in range(4):
            thread._process(frame())
        assert len(engine.shapes) == 4 and thread.skipped == 0
    finally:
        thread.service.shutdown()


def show_text(thread: PipelineThread, engine: FakeEngine, lines: list[TextLine], frames: int = 60):
    """Make the engine read `lines` and process frames until a translation
    of the first line's text is drawn; returns the render."""
    engine.lines = lines
    wanted = lines[0].text.upper()
    for _ in range(frames):
        render = thread._process(frame())
        if any(wanted in b.lines for b in render):
            return render
        time.sleep(0.02)
    raise AssertionError(f"{wanted!r} never rendered")


def test_subtitle_zone_keeps_one_font_size_across_lines_of_different_box_heights() -> None:
    engine = FakeEngine()
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0)
    try:
        sizes = []
        # Boxes 40, 36 and 44 px tall (descenders, none, a tall glyph), then an odd 48 px one.
        for text, height in (("First line here.", 40), ("Second line.", 36), ("Third one!", 44), ("Fourth.", 48)):
            (block,) = show_text(thread, engine, [line(text, 300, 30, 700, 30 + height)])
            sizes.append(block.font_px)
        assert thread.zone_style.locked and thread.zone_style.line_height == 40
        assert sizes[2] == sizes[3] == 32  # locked at 0.8 * 40; the 48 px box does not move it
        assert sizes[0] in (32,) and 28 <= sizes[1] <= 32  # while learning: the running median, never the odd box
        assert block.position == "bottom" and block.background == "pill"
    finally:
        thread.service.shutdown()


def test_subtitle_text_colour_is_sampled_unless_set() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0)
    try:
        (block,) = process_until(thread, lambda r: bool(r))
        assert block.fg == tuple(int(v) for v in frame().image[0, 0][::-1])  # the frame's colour, as RGB
    finally:
        thread.service.shutdown()
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0, subtitle_color=(255, 230, 0))
    try:
        (block,) = process_until(thread, lambda r: bool(r))
        assert block.fg == (255, 230, 0)
    finally:
        thread.service.shutdown()


def test_off_centre_text_in_the_zone_is_not_a_subtitle() -> None:
    prompt = line("Hold F to open", 20, 30, 220, 60)  # a prompt at the left edge of the strip
    subtitle = line("Stay close.", 300, 20, 700, 60)  # centred in the 1000 px wide strip
    engine = FakeEngine([prompt, subtitle])
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0)
    try:
        render = process_until(thread, lambda r: bool(r))
        for _ in range(5):
            render = thread._process(frame())
        assert [b.lines for b in render] == [["STAY CLOSE."]]
        assert thread.service.stats["items"] == 1  # the prompt was never sent for translation
    finally:
        thread.service.shutdown()
    # Tolerance 0 turns the rule off.
    engine = FakeEngine([prompt, subtitle])
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0, subtitle_center_tolerance=0)
    try:
        render = process_until(thread, lambda r: len(r) == 2)
        assert sorted(b.lines[0] for b in render) == ["HOLD F TO OPEN", "STAY CLOSE."]
    finally:
        thread.service.shutdown()


def test_text_of_another_size_is_not_a_subtitle_once_the_size_is_known() -> None:
    engine = FakeEngine()
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0)
    try:
        for text in ("First line here.", "Second line.", "Third one!"):
            show_text(thread, engine, [line(text, 300, 30, 700, 70)])  # 40 px lines: the size locks
        small = line("Objective updated", 350, 10, 650, 24)  # 14 px: HUD text, centred
        engine.lines = [small]
        for _ in range(8):
            render = thread._process(frame())
            time.sleep(0.02)
        assert render == []
        assert not any(b.text == small.text and b.translation for b in thread._tracker.blocks)
    finally:
        thread.service.shutdown()


def test_translations_are_requested_one_sighting_early_and_shown_once_confirmed() -> None:
    # Far enough apart vertically that the tracker keeps them as two blocks.
    engine = FakeEngine([line("Ok", 450, 2, 550, 22), line("Stay close.", 300, 60, 700, 95)])
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0, subtitle_size_tolerance=0)
    try:
        assert thread._process(frame()) == []  # first sighting: the long line is requested, nothing is shown
        assert thread.service.stats["items"] == 1
        thread._process(frame())  # stable_frames 1: the short one (two sightings to confirm) is requested
        assert thread.service.stats["items"] == 2
        render = process_until(thread, lambda r: len(r) == 2)  # both confirmed, both answers already in
        assert sorted(b.lines[0] for b in render) == ["OK", "STAY CLOSE."]
    finally:
        thread.service.shutdown()


def test_settings_change_on_the_fly_keeps_the_blocks_unless_the_reading_changed() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0)
    try:
        (block,) = process_until(thread, lambda r: bool(r))
        assert not block.bold
        (tracked,) = thread._tracker.blocks
        thread.update_config(replace(thread.cfg, subtitle_bold=True))  # a change of look
        (block,) = thread._process(frame())
        assert block.bold and thread._tracker.blocks == [tracked]  # taken up, nothing forgotten
        thread.update_config(replace(thread.cfg, roi=(0, 550, WIDTH, 700)))  # a change of what is read
        thread._process(frame())
        assert thread.cfg.roi == (0, 550, WIDTH, 700)
        (fresh,) = thread._tracker.blocks  # read afresh: a new block, confirmed and translated from scratch
        assert fresh is not tracked and fresh.stable_frames == 0 and fresh.translation is None
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
