"""The pipeline thread's per-frame work with a fake OCR engine: which region
is read, the full-scan cadence, the frame-change gate, settings changed on
the fly, and translations reaching the render blocks (a cached one without
a request). No capture, no window, no real OCR."""

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
from gametl.overlay.paint import ChatCard, ChatLine
from gametl.translate.base import TranslationRequest
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


def test_full_scan_cadence_including_every_read() -> None:
    engine = FakeEngine()
    thread = pipeline(engine, roi=STRIP, render="inplace", full_scan_every=3, change_threshold=0)
    for _ in range(6):
        thread.track_frame(frame())
    # reads 1 and 4 sweep the whole area as well as the strip
    assert [len(s) == 3 and s[0] for s in engine.shapes] == [100, HEIGHT, 100, 100, 100, HEIGHT, 100, 100]

    engine = FakeEngine()
    thread = pipeline(engine, roi=STRIP, render="inplace", full_scan_every=1, change_threshold=0)
    for _ in range(3):
        thread.track_frame(frame())
    assert [s[0] for s in engine.shapes] == [100, HEIGHT] * 3  # every read, not never


def test_subtitle_mode_never_sweeps_outside_the_zone() -> None:
    engine = FakeEngine()
    thread = pipeline(engine, roi=STRIP, render="subtitle", full_scan_every=1, change_threshold=0)
    for _ in range(3):
        thread.track_frame(frame())
    assert [s[0] for s in engine.shapes] == [100] * 3  # the strip only: nothing outside it is ever drawn


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


class RecordingTranslator(UppercaseTranslator):
    """Upper case, and every request's texts kept."""

    def __init__(self) -> None:
        self.requests: list[list[str]] = []
        self.speakers: list[list[str] | None] = []

    def translate(self, request: TranslationRequest) -> list[str]:
        self.requests.append(list(request.texts))
        self.speakers.append(request.speakers)
        return super().translate(request)


def test_chat_mode_keeps_a_transcript_with_the_speakers() -> None:
    engine = FakeEngine([line("Casey: Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="chat", chat_corner="top-left", change_threshold=0)
    translator = thread.service.translator = RecordingTranslator()
    try:
        (card,) = process_until(thread, lambda r: bool(r))
        assert isinstance(card, ChatCard)
        (said,) = card.lines
        assert (said.speaker, said.text, said.speaker_index) == (
            "Casey",
            "STAY CLOSE.",
            0,
        )  # the name kept, words translated
        assert said.stamp == time.strftime("%H:%M:%S") or said.stamp < time.strftime("%H:%M:%S")  # said just now
        thread.update_config(replace(thread.cfg, chat_timestamps=False))
        (card,) = thread._process(frame())
        assert card.lines == [ChatLine("Casey", "STAY CLOSE.", 0)]  # no stamp
        thread.update_config(replace(thread.cfg, chat_timestamps=True))
        assert card.corner == "top-left" and card.zone == STRIP and card.area == (0, 0, WIDTH, HEIGHT)
        assert card.covers == []  # hide_source off
        assert translator.requests == [["Stay close."]] and translator.speakers == [["Casey"]]
        for _ in range(3):  # the line seen again is not said again
            (card,) = thread._process(frame())
        assert len(card.lines) == 1
        # The next line at the same spot joins the transcript; the first stays.
        engine.lines = [line("Alan: Go.", 300, 20, 700, 60)]
        (card,) = process_until(thread, lambda r: r and len(r[0].lines) == 2)
        assert [(ln.speaker, ln.text, ln.speaker_index) for ln in card.lines] == [
            ("Casey", "STAY CLOSE.", 0),
            ("Alan", "GO.", 1),
        ]
        # The card's words are the cache's keys: the line comes back as a cache hit.
        assert thread.service.cache.get("Go.", "tr") == "GO."
        thread.update_config(replace(thread.cfg, subtitle_hide_source=True))
        (card,) = thread._process(frame())
        assert card.covers == [(300, 620, 700, 660)]  # the live source line is hidden under a band
        thread.update_config(replace(thread.cfg, subtitle_hide_source=False, chat_seconds=0.01))
        time.sleep(0.02)
        (card,) = thread._process(frame())
        assert [ln.text for ln in card.lines] == ["GO."]  # the line still on screen stays, however old; the other went
        engine.lines = []
        time.sleep(0.02)
        assert process_until(thread, lambda r: r == []) == []  # off screen and past its time: nothing is drawn
    finally:
        thread.service.shutdown()


def test_a_rescan_or_a_pause_does_not_say_a_line_twice() -> None:
    engine = FakeEngine([line("Casey: Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="chat", change_threshold=0)
    try:
        process_until(thread, lambda r: bool(r))
        for _ in range(3):
            thread._process(frame())
        thread._forget_blocks(reset_style=True)  # what rescan, unpause and a changed area do
        (card,) = process_until(thread, lambda r: thread._tracker.blocks and thread._tracker.blocks[0].translation)
        assert [ln.text for ln in card.lines] == ["STAY CLOSE."]  # found again by its words, not said again
        assert thread._transcript.utterances[0].block_id == thread._tracker.blocks[0].id  # and followed anew
    finally:
        thread.service.shutdown()


def test_the_card_ages_on_a_still_screen_and_a_mode_switch_clears_it() -> None:
    engine = FakeEngine([line("Casey: Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="chat", change_threshold=0, chat_seconds=0.2)
    emitted: list[list] = []
    thread.blocks_ready.connect(emitted.append)
    try:
        process_until(thread, lambda r: bool(r))
        engine.lines = []  # the line goes; the game then stops redrawing
        process_until(thread, lambda r: not thread._tracker.blocks)
        assert len(thread._transcript) == 1  # just gone: still within its time
        time.sleep(0.25)
        thread._idle()  # no frame arrives: the loop ticks the transcript instead
        assert emitted[-1] == []  # the card went without a frame
        engine.lines = [line("Casey: Stay close.", 300, 20, 700, 60)]
        process_until(thread, lambda r: bool(r))
        thread.update_config(replace(thread.cfg, render="subtitle"))
        thread._process(frame())
        assert len(thread._transcript) == 0  # another mode: the transcript starts afresh
    finally:
        thread.service.shutdown()


def test_a_screen_read_page_shows_on_the_card_in_every_mode() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0)
    try:
        (block,) = process_until(thread, lambda r: bool(r))
        assert thread.last_frame is not None and thread.last_frame.width == WIDTH
        page = [ChatLine("Note", "Kapı kilitli.\nAnahtar masada.", -1, "21:36:05")]
        thread.set_page(page)
        subtitle, card = thread._process(frame())
        assert subtitle.lines == block.lines and isinstance(card, ChatCard)  # the subtitle stays, the page joins
        assert card.lines == page and card.covers == []
        thread.update_config(replace(thread.cfg, render="chat"))
        (card,) = process_until(thread, lambda r: r and len(r[0].lines) == 2)
        assert [ln.speaker for ln in card.lines] == ["", "Note"]  # the transcript first, the page last
        thread.set_page([])
        (card,) = thread._process(frame())
        assert [ln.speaker for ln in card.lines] == [""] and thread.page == []
    finally:
        thread.service.shutdown()


def test_in_place_mode_translates_a_label_whole() -> None:
    engine = FakeEngine([line("Objective: Find the key", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="inplace", change_threshold=0)
    try:
        (block,) = process_until(thread, lambda r: bool(r))
        assert block.lines == ["OBJECTIVE: FIND THE KEY"]  # a label, not a speaker: nothing split off
        assert thread.service.cache.get("Objective: Find the key", "tr") is not None
    finally:
        thread.service.shutdown()


def test_a_speaker_name_stays_in_front_of_a_subtitle() -> None:
    engine = FakeEngine([line("Casey: Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="subtitle", change_threshold=0)
    try:
        (block,) = process_until(thread, lambda r: bool(r))
        assert block.lines == ["Casey: STAY CLOSE."]  # the words translated, the name as the game printed it
        assert thread.service.cache.get("Stay close.", "tr") == "STAY CLOSE."  # cached without the name
    finally:
        thread.service.shutdown()


def test_a_cached_line_is_shown_and_never_sent() -> None:
    translator = RecordingTranslator()
    cache = TranslationCache()
    cache.put("Stay close.", "tr", "Yakın dur.")
    service = TranslationService(translator, cache, target_lang="tr", source_lang="en")
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = PipelineThread(0, engine, service, PipelineConfig(roi=STRIP, render="subtitle", change_threshold=0))
    try:
        (block,) = process_until(thread, lambda r: bool(r))
        for _ in range(5):  # a line seen again and again still never reaches the translator
            thread._process(frame())
        assert block.lines == ["Yakın dur."]
        assert translator.requests == []
        assert cache.get("Stay close.", "tr") == "Yakın dur."
    finally:
        service.shutdown()


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


def test_a_shown_subtitle_keeps_its_place_and_size_when_re_read() -> None:
    engine = FakeEngine()
    thread = pipeline(engine, roi=STRIP, render="subtitle", subtitle_position="source", change_threshold=0)
    try:
        (first,) = show_text(thread, engine, [line("Hold this line.", 320, 30, 680, 70)])
        assert (first.font_px, first.anchor_y) == (32, 650)  # crop y 30..70 sits at 630..670 in the frame
        # The same line read again 6 px lower and wider (a fade-in ended): the tracker adopts the box...
        (again,) = show_text(thread, engine, [line("Hold this line.", 300, 36, 700, 76)])
        assert again.bbox == (300, 636, 700, 676)
        # ...but what is drawn stays put, at the size it had.
        assert (again.font_px, again.anchor_y) == (first.font_px, first.anchor_y)
        # A new line gets its own anchor.
        (fresh,) = show_text(thread, engine, [line("Another line.", 320, 20, 680, 60)])
        assert fresh.anchor_y == 640 and (1, "Hold this line.") not in thread._held
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
        assert block.weight == "semibold" and block.hide_source is False  # the app's own defaults
        (tracked,) = thread._tracker.blocks
        thread.update_config(replace(thread.cfg, subtitle_weight="bold"))  # a change of look
        (block,) = thread._process(frame())
        assert block.weight == "bold" and thread._tracker.blocks == [tracked]  # taken up, nothing forgotten
        thread.update_config(replace(thread.cfg, roi=(0, 550, WIDTH, 700)))  # a change of what is read
        thread._process(frame())
        assert thread.cfg.roi == (0, 550, WIDTH, 700)
        (fresh,) = thread._tracker.blocks  # read afresh: a new block, confirmed and translated from scratch
        assert fresh is not tracked and fresh.stable_frames == 0 and fresh.translation is None
    finally:
        thread.service.shutdown()


def test_subtitle_tests_and_counts_change_without_forgetting_the_blocks() -> None:
    engine = FakeEngine([line("Stay close.", 300, 20, 700, 60)])
    thread = pipeline(engine, roi=STRIP, render="subtitle", subtitle_position="source", change_threshold=0)
    try:
        (shown,) = process_until(thread, lambda r: bool(r))
        (tracked,) = thread._tracker.blocks
        held = dict(thread._held)
        changed = replace(
            thread.cfg, subtitle_size_tolerance=0.5, subtitle_center_tolerance=0.2, stable_frames=2, max_missing=9
        )
        thread.update_config(changed)  # judged afresh each frame: nothing to forget
        (again,) = thread._process(frame())
        assert thread._tracker.blocks == [tracked] and thread._tracker.max_missing == 9
        assert thread._held == held and (again.font_px, again.anchor_y) == (shown.font_px, shown.anchor_y)
        thread.update_config(replace(thread.cfg, subtitle_weight="bold"))  # a look alone keeps the held size too
        thread._process(frame())
        assert thread._held == held
        thread.update_config(replace(thread.cfg, subtitle_font_px=40))  # the held size came from the old one
        (bigger,) = thread._process(frame())
        assert bigger.font_px == 40 and thread._tracker.blocks == [tracked]
    finally:
        thread.service.shutdown()


def test_frames_of_another_size_ask_for_a_new_configuration_once() -> None:
    thread = pipeline(FakeEngine(), roi=STRIP, frame_size=(WIDTH, HEIGHT), change_threshold=0)
    asked: list[bool] = []
    thread.resized.connect(lambda: asked.append(True))
    try:
        thread._process(frame())
        assert asked == []  # the size the boxes were worked out for
        bigger = Frame(image=np.full((1080, 1920, 3), 20, dtype=np.uint8), timestamp=time.perf_counter())
        for _ in range(3):
            thread._process(bigger)  # read meanwhile, with the old boxes
        assert asked == [True]  # once, not on every frame
        thread.update_config(replace(thread.cfg, frame_size=(1920, 1080), roi=(0, 900, 1920, 1080)))
        thread._process(bigger)
        thread._process(frame())  # and back: a new mismatch is reported again
        assert asked == [True, True]
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
