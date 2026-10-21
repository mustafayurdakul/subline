from __future__ import annotations

import numpy as np

from gametl.ocr.base import TextLine
from gametl.tracking.blocks import (
    BlockTracker,
    containment,
    group_lines,
    iou,
    merge_row_fragments,
    text_similarity,
)


def line(text: str, x0: int, y0: int, x1: int, y1: int, conf: float = 0.95) -> TextLine:
    quad = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)
    return TextLine(text, quad, conf)


# -- helpers -------------------------------------------------------------------


def test_iou_overlap_and_disjoint() -> None:
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - 1 / 3) < 1e-6


def test_containment() -> None:
    assert containment((0, 0, 100, 10), (80, 2, 100, 8)) == 1.0
    assert containment((0, 0, 10, 10), (20, 0, 30, 10)) == 0.0


def test_text_similarity_tolerates_ocr_jitter() -> None:
    assert text_similarity("Hello world", "hello  world") == 1.0
    assert text_similarity("Stay close, and keep your voice down.", "Stay close, and keep your vo1ce down.") > 0.9
    assert text_similarity("keep your voice down.", "keep your voice down") > 0.9  # dropped full stop
    assert text_similarity("Stay close", "The bridge is gone") < 0.5


def test_text_similarity_sees_typewriter_growth_as_change() -> None:
    assert text_similarity("Stay cl", "Stay clo") > 0.9  # one character: could be jitter
    assert text_similarity("Stay cl", "Stay close") == 0.0
    assert text_similarity("Stay close, and keep", "Stay close, and keep your voice") == 0.0


def test_row_fragments_merge_into_one_line() -> None:
    merged = merge_row_fragments([line("9s", 205, 42, 240, 68), line("HP 87/100 Ammo 24", 20, 40, 200, 70)])
    assert len(merged) == 1
    assert merged[0].text == "HP 87/100 Ammo 24 9s"
    assert merged[0].bbox == (20, 40, 240, 70)
    far = merge_row_fragments([line("left", 20, 40, 200, 70), line("right", 400, 40, 600, 70)])
    assert len(far) == 2


# -- grouping ------------------------------------------------------------------


def test_two_subtitle_lines_form_one_block_top_to_bottom() -> None:
    groups = group_lines([line("second", 300, 660, 900, 700), line("first", 280, 612, 920, 652)])
    assert len(groups) == 1
    assert [ln.text for ln in groups[0]] == ["first", "second"]


def test_hud_and_subtitle_stay_separate() -> None:
    groups = group_lines([line("HP 87", 20, 40, 200, 70), line("subtitle", 300, 620, 900, 660)])
    assert len(groups) == 2


def test_side_by_side_lines_stay_separate() -> None:
    groups = group_lines([line("left", 20, 40, 200, 70), line("right", 400, 40, 600, 70)])
    assert len(groups) == 2


# -- tracking ------------------------------------------------------------------


def test_block_keeps_id_and_gains_stability() -> None:
    tracker = BlockTracker()
    first = tracker.update([line("Hello there", 300, 620, 900, 660)])
    second = tracker.update([line("Hello there", 301, 621, 901, 661)])
    assert [b.id for b in first] == [b.id for b in second]
    assert second[0].stable_frames == 1
    assert second[0].text == "Hello there"


def test_small_box_jitter_is_ignored_but_real_moves_follow() -> None:
    tracker = BlockTracker(jitter_px=3)
    (block,) = tracker.update([line("Hello there", 300, 620, 900, 660)])
    tracker.update([line("Hello there", 302, 618, 903, 661)])
    assert block.bbox == (300, 620, 900, 660)  # wobble absorbed: no flicker
    tracker.update([line("Hello there", 300, 610, 900, 650)])
    assert block.bbox == (300, 610, 900, 650)  # a real move (still overlapping) is followed


def test_text_change_is_confirmed_before_it_replaces_the_block() -> None:
    tracker = BlockTracker()
    (block,) = tracker.update([line("Hello there", 300, 620, 900, 660)])
    tracker.update([line("Hello there", 300, 620, 900, 660)])
    block.translation = "HELLO THERE"
    # First sighting of new text: pending; the old translation is hidden at
    # once (it would be drawn over different text), the old reading kept.
    (same,) = tracker.update([line("Where were you?", 320, 620, 880, 660)])
    assert same.id == block.id
    assert same.text == "Hello there"
    assert same.translation is None
    assert same.pending_text == "Where were you?"
    # Second sighting confirms it: text replaced, translation cleared, already stable.
    (same,) = tracker.update([line("Where were you?", 320, 620, 880, 660)])
    assert same.text == "Where were you?"
    assert same.translation is None
    assert same.stable_frames == 1
    assert same.bbox == (320, 620, 880, 660)


def test_one_frame_ocr_miss_keeps_the_reading_but_hides_the_translation() -> None:
    tracker = BlockTracker()
    (block,) = tracker.update([line("Hello there", 300, 620, 900, 660)])
    block.translation = "x"
    (same,) = tracker.update([line("Garbage", 300, 620, 900, 660)])
    assert same.translation is None  # hidden for this frame
    (same,) = tracker.update([line("Hello there", 300, 620, 900, 660)])
    assert same.text == "Hello there"  # reading never replaced: no retranslation, cache restores it
    assert same.id == block.id
    assert same.pending_text is None
    assert same.stable_frames == 1


def test_typewriter_reveal_settles_only_when_typing_stops() -> None:
    tracker = BlockTracker()
    texts = ["Stay", "Stay close,", "Stay close, and keep", "Stay close, and keep your voice down."]
    for t in texts:
        (block,) = tracker.update([line(t, 300, 620, 300 + 20 * len(t), 660)])
        assert block.stable_frames == 0  # never stable while growing
    (block,) = tracker.update([line(texts[-1], 300, 620, 300 + 20 * len(texts[-1]), 660)])
    assert block.text == texts[-1]
    assert block.stable_frames == 1


def test_ocr_jitter_does_not_reset_block() -> None:
    tracker = BlockTracker()
    (block,) = tracker.update([line("Stay close, and keep your voice down.", 300, 620, 900, 660)])
    block.translation = "x"
    (same,) = tracker.update([line("Stay close, and keep your vo1ce down.", 300, 620, 900, 660)])
    assert same.translation == "x"
    assert same.stable_frames == 1
    assert same.text == "Stay close, and keep your voice down."


def test_block_survives_max_missing_frames_then_drops() -> None:
    tracker = BlockTracker(max_missing=3)
    tracker.update([line("Hello", 300, 620, 900, 660)])
    for _ in range(3):
        assert len(tracker.update([])) == 1
    assert tracker.update([]) == []


def test_blocks_outside_scanned_region_are_untouched() -> None:
    tracker = BlockTracker(max_missing=1)
    tracker.update([line("HUD", 20, 40, 200, 70), line("subtitle", 300, 620, 900, 660)])
    strip = (0, 600, 1000, 700)
    for _ in range(5):
        blocks = tracker.update([line("subtitle", 300, 620, 900, 660)], scanned=strip)
    texts = sorted(b.text for b in blocks)
    assert texts == ["HUD", "subtitle"]
    hud = next(b for b in blocks if b.text == "HUD")
    assert hud.missing_frames == 0


def test_digit_change_is_a_real_change() -> None:
    assert text_similarity("HP 87/100 Ammo 24 9s", "HP 87/100 Ammo 24 2s") == 0.0
    tracker = BlockTracker()
    (block,) = tracker.update([line("HP 87/100 Ammo 24 9s", 20, 40, 240, 70)])
    block.translation = "old"
    for _ in range(2):  # seen twice: confirmed
        (same,) = tracker.update([line("HP 87/100 Ammo 24 2s", 20, 40, 240, 70)])
    assert same.id == block.id
    assert same.translation is None
    assert same.text == "HP 87/100 Ammo 24 2s"


def test_split_fragment_does_not_spawn_a_block() -> None:
    tracker = BlockTracker()
    (block,) = tracker.update([line("HP 87/100 Ammo 24 9s", 20, 40, 240, 70)])
    # Next frame the detector splits the tail off as its own small line.
    blocks = tracker.update([line("HP 87/100 Ammo 24", 20, 40, 200, 70), line("9s", 205, 42, 240, 68)])
    assert [b.id for b in blocks] == [block.id]
    assert blocks[0].stable_frames == 1
    assert blocks[0].bbox == (20, 40, 240, 70)


def test_vertical_fragment_keeps_full_box_until_confirmed() -> None:
    tracker = BlockTracker()
    (block,) = tracker.update([line("first", 280, 612, 920, 652), line("second", 300, 660, 900, 700)])
    block.translation = "x"
    # One frame only sees the first line: pending, box kept, translation hidden.
    (same,) = tracker.update([line("first", 280, 612, 920, 652)])
    assert same.id == block.id
    assert same.bbox == (280, 612, 920, 700)
    assert same.translation is None
    # Seen again: the second line really is gone.
    (same,) = tracker.update([line("first", 280, 612, 920, 652)])
    assert same.text == "first"
    assert same.bbox == (280, 612, 920, 652)
    assert same.translation is None


def test_new_block_at_other_position_gets_new_id() -> None:
    tracker = BlockTracker()
    (a,) = tracker.update([line("A", 300, 620, 900, 660)])
    blocks = tracker.update([line("A", 300, 620, 900, 660), line("B", 20, 40, 200, 70)])
    assert len(blocks) == 2
    assert {b.id for b in blocks} == {a.id, a.id + 1}
