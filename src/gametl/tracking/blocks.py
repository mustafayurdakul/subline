"""Group OCR lines into blocks and track the blocks across frames.

A block is one subtitle, one dialogue box, one menu label: a stack of lines
that belong together. The tracker gives each block an id that survives from
frame to frame, counts how many consecutive frames its text has been
unchanged (the stability gate), and keeps a block alive for a few frames
after OCR stops seeing it (hysteresis against flicker).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..ocr.base import TextLine
from ..textutil import text_similarity

Box = tuple[int, int, int, int]
BGR = tuple[int, int, int]


# -- geometry ------------------------------------------------------------------


def _intersection(a: Box, b: Box) -> int:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0
    return (ix1 - ix0) * (iy1 - iy0)


def area(a: Box) -> int:
    return max(0, a[2] - a[0]) * max(0, a[3] - a[1])


def iou(a: Box, b: Box) -> float:
    inter = _intersection(a, b)
    if inter == 0:
        return 0.0
    return inter / float(area(a) + area(b) - inter)


def containment(a: Box, b: Box) -> float:
    """Intersection over the smaller area: 1.0 when one box lies inside the other."""
    inter = _intersection(a, b)
    if inter == 0:
        return 0.0
    return inter / float(max(1, min(area(a), area(b))))


def intersects(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def union(boxes: list[Box]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


# -- grouping ------------------------------------------------------------------


def _row_overlap(a: Box, b: Box) -> float:
    """Vertical overlap as a fraction of the shorter box height."""
    inter = min(a[3], b[3]) - max(a[1], b[1])
    return inter / float(max(1, min(a[3] - a[1], b[3] - b[1])))


def _merged_line(parts: list[TextLine]) -> TextLine:
    x0, y0, x1, y1 = union([p.bbox for p in parts])
    quad = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)
    return TextLine(
        text=" ".join(p.text for p in parts),
        quad=quad,
        confidence=min(p.confidence for p in parts),
    )


def merge_row_fragments(lines: list[TextLine], gap_factor: float = 1.0) -> list[TextLine]:
    """Join pieces of one row that the detector split (wide word gaps, HUD
    columns): same baseline (vertical overlap of at least half) and a
    horizontal gap of at most `gap_factor` times the smaller height."""
    ordered = sorted(lines, key=lambda line: (line.bbox[0], line.bbox[1]))
    rows: list[list[TextLine]] = []
    for line in ordered:
        for row in rows:
            last_box, box = row[-1].bbox, line.bbox
            height = min(last_box[3] - last_box[1], box[3] - box[1])
            gap = box[0] - last_box[2]
            if _row_overlap(last_box, box) >= 0.5 and -0.2 * height <= gap <= gap_factor * height:
                row.append(line)
                break
        else:
            rows.append([line])
    return [row[0] if len(row) == 1 else _merged_line(row) for row in rows]


def group_lines(lines: list[TextLine], gap_factor: float = 0.7, overlap_min: float = 0.2) -> list[list[TextLine]]:
    """Stack lines into blocks, top to bottom, after merging row fragments.

    A line joins the block above it when the vertical gap is under
    `gap_factor` times the smaller line height and the two overlap
    horizontally by at least `overlap_min` of the narrower line. Lines on
    the same row (strongly overlapping vertically) stay separate.
    """
    ordered = sorted(merge_row_fragments(lines), key=lambda line: (line.bbox[1], line.bbox[0]))
    groups: list[list[TextLine]] = []
    for line in ordered:
        x0, y0, x1, _ = line.bbox
        for group in groups:
            last = group[-1]
            lx0, _, lx1, ly1 = last.bbox
            height = max(1.0, min(last.height, line.height))
            gap = y0 - ly1
            if gap < -0.5 * height or gap > gap_factor * height:
                continue
            overlap = min(x1, lx1) - max(x0, lx0)
            if overlap < overlap_min * min(x1 - x0, lx1 - lx0):
                continue
            group.append(line)
            break
        else:
            groups.append([line])
    return groups


# -- tracking ------------------------------------------------------------------


@dataclass(slots=True)
class TextBlock:
    id: int
    bbox: Box
    lines: list[TextLine]
    text: str  # line texts joined with "\n"
    confidence: float
    stable_frames: int = 0  # consecutive updates with unchanged text
    missing_frames: int = 0  # consecutive scanned frames without a match
    pending_text: str | None = None  # a different reading, not yet confirmed
    pending_frames: int = 0  # consecutive frames the pending reading was seen (0 = once)
    translation: str | None = None
    draft: bool = False  # the translation is a draft; the final one is still on its way
    colors: tuple[BGR, BGR] | None = None  # (background, text) sampled from the frame
    busy: bool = False  # the background behind the text is too varied for a flat patch
    contrast: float = 255.0  # luminance difference between text and background

    @property
    def line_texts(self) -> list[str]:
        return self.text.split("\n")


class BlockTracker:
    def __init__(
        self,
        min_iou: float = 0.3,
        max_missing: int = 3,
        same_text_ratio: float = 0.9,
        gap_factor: float = 0.7,
        min_containment: float = 0.8,
        confirm_frames: int = 1,
        jitter_px: int = 3,
    ) -> None:
        self.min_iou = min_iou
        self.max_missing = max_missing
        self.same_text_ratio = same_text_ratio
        self.gap_factor = gap_factor
        self.min_containment = min_containment
        self.confirm_frames = confirm_frames  # extra sightings before a changed reading replaces the text
        self.jitter_px = jitter_px  # box edges moving up to this many pixels are OCR jitter, not a move
        self.blocks: list[TextBlock] = []
        self._next_id = 1

    def update(self, lines: list[TextLine], scanned: Box | None = None) -> list[TextBlock]:
        """Feed one frame's OCR lines. `scanned` is the frame region that was
        read; blocks outside it are left untouched (neither matched nor
        counted missing). None means the whole frame. Returns the live blocks."""
        # 1. This frame's lines become candidate blocks; only known blocks inside
        #    the read region take part in matching.
        groups = group_lines(lines, self.gap_factor)
        group_boxes = [union([line.bbox for line in group]) for group in groups]
        candidates = [b for b in self.blocks if scanned is None or intersects(b.bbox, scanned)]
        prior_boxes = [b.bbox for b in self.blocks]

        # 2. Score every (group, block) pair by overlap, or by containment when
        #    one box lies mostly inside the other (the detector split or merged
        #    a line between frames).
        pairs: list[tuple[float, int, TextBlock]] = []
        for index, box in enumerate(group_boxes):
            for block in candidates:
                score = iou(box, block.bbox)
                if score < self.min_iou and containment(box, block.bbox) >= self.min_containment:
                    score = self.min_iou  # eligible, ranked below real overlaps
                if score >= self.min_iou:
                    pairs.append((score, index, block))
        pairs.sort(key=lambda pair: -pair[0])

        # 3. Greedy one-to-one assignment, best pair first; a match refreshes the block.
        matched_groups: set[int] = set()
        matched_blocks: set[int] = set()
        for _score, index, block in pairs:
            if index in matched_groups or block.id in matched_blocks:
                continue
            matched_groups.add(index)
            matched_blocks.add(block.id)
            self._refresh(block, groups[index], group_boxes[index])

        # 4. Known blocks that were in the read region but not seen age one frame;
        #    after max_missing frames they are dropped.
        for block in candidates:
            if block.id not in matched_blocks:
                block.missing_frames += 1
        self.blocks = [b for b in self.blocks if b.missing_frames <= self.max_missing]

        # 5. Unmatched groups become new blocks, unless they are a fragment of a
        #    block that exists (or existed a moment ago at that spot).
        for index, group in enumerate(groups):
            if index in matched_groups:
                continue
            box = group_boxes[index]
            if any(containment(box, prior) >= self.min_containment for prior in prior_boxes):
                continue
            self.blocks.append(self._new(group, box))
        return list(self.blocks)

    def _new(self, group: list[TextLine], bbox: Box) -> TextBlock:
        block = TextBlock(
            id=self._next_id,
            bbox=bbox,
            lines=group,
            text="\n".join(line.text for line in group),
            confidence=min(line.confidence for line in group),
        )
        self._next_id += 1
        return block

    def _refresh(self, block: TextBlock, group: list[TextLine], bbox: Box) -> None:
        """Fold one new reading of a block into it.

        Same text (allowing OCR jitter): stability grows and the box follows
        the reading, unless the reading is only a fragment of the known text
        or the move is within the jitter allowance.

        Different text: it becomes a pending reading and replaces the text
        only once it has been seen `confirm_frames` more times. Until then
        the old text and box stay, so a one-frame OCR miss or a typewriter
        reveal does not spawn a new block. The translation is hidden at once,
        since the screen no longer shows the text it belongs to; if the
        reading turns out to be jitter, the cache restores it a frame later.
        """
        text = "\n".join(line.text for line in group)
        block.lines = group
        block.confidence = min(line.confidence for line in group)
        block.missing_frames = 0

        # Same text as before (within OCR jitter): one frame more stable.
        if text_similarity(text, block.text) >= self.same_text_ratio:
            block.stable_frames += 1
            block.pending_text = None
            block.pending_frames = 0
            fragment = area(bbox) < area(block.bbox) and containment(bbox, block.bbox) >= self.min_containment
            jitter = max(abs(a - b) for a, b in zip(bbox, block.bbox, strict=True)) <= self.jitter_px
            if not fragment and not jitter:
                block.bbox = bbox
            return

        # Different text: count the frames in a row this new reading has been seen.
        if block.pending_text is not None and text_similarity(text, block.pending_text) >= self.same_text_ratio:
            block.pending_frames += 1
        else:
            block.pending_text = text
            block.pending_frames = 0
        block.translation = None
        block.draft = False

        # Seen often enough: the new reading replaces the old one.
        if block.pending_frames >= self.confirm_frames:
            block.text = block.pending_text
            block.stable_frames = block.pending_frames
            block.pending_text = None
            block.pending_frames = 0
            block.colors = None
            block.bbox = bbox
