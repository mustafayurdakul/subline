"""The capture -> OCR -> track -> translate loop, on its own thread.

Emits a list of RenderBlocks for the overlay after every processed frame.
The UI thread never waits on OCR or translation.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from ..capture.base import Frame
from ..capture.wgc import WgcWindowCapture
from ..geometry import RGB, Box
from ..layout.colors import analyze_colors, bgr_to_rgb
from ..layout.style import StyleMemory, ZoneStyle, line_height_of
from ..ocr.base import OcrEngine, TextLine
from ..overlay.window import RenderBlock
from ..textutil import letter_count
from ..tracking.blocks import BlockTracker, TextBlock, intersects
from ..tracking.filters import LineFilter
from ..translate.service import TranslationService


@dataclass(slots=True)
class PipelineConfig:
    area: Box | None = None  # frame pixels considered at all (the client area); None = whole frame
    roi: Box | None = None  # frame pixels read and translated; None = the whole area every frame
    fps: float = 10.0  # capture cap
    full_scan_every: int = 0  # with a roi: also sweep the rest of the area every N frames (0 = never)
    stable_frames: int = 1  # confirming frames before translating
    max_missing: int = 3  # frames a block survives without being seen
    style: str = "auto"  # in-place style: auto | patch | pill | outline; auto = patch unless the background is busy
    line_filter: LineFilter | None = None  # ignore zones and patterns
    # subtitle mode (needs a roi): one fixed style, centred in the zone
    render: str = "subtitle"  # "subtitle" | "inplace"
    subtitle_font_px: int = 0  # 0 = the zone's learned line height (locked after a few lines)
    subtitle_color: RGB | None = None  # None = the game's own subtitle colour, sampled
    subtitle_background: str = "pill"  # "pill" | "shadow" | "none"
    subtitle_pill_alpha: int = 230
    subtitle_bold: bool = False
    subtitle_position: str = "bottom"  # "bottom" | "source" | "center"
    subtitle_hide_source: bool = True
    # Which blocks in the zone are subtitles rather than HUD text: centred in the
    # zone (within a fraction of its width) and about the learned line height.
    subtitle_center_tolerance: float = 0.10  # 0 = off
    subtitle_size_tolerance: float = 0.35  # 0 = off
    # A text with fewer letters than this is a fragment as often as a word: it
    # must hold for `short_text_frames` frames before it is translated.
    short_text_letters: int = 4
    short_text_frames: int = 2
    grow_margin: int = 4  # px kept between a grown box and its neighbours
    # Frame diff: OCR is skipped while the read region looks the same as the
    # last frame read (mean absolute difference of a 1/8-scale grey thumbnail,
    # 0..255, below the threshold) and every tracked block is settled.
    diff_threshold: float = 1.0  # 0 = OCR every frame
    max_skipped: int = 20  # frames skipped in a row before OCR runs regardless
    debug: bool = False  # also emit outlines of every tracked block and per-frame stats
    dump_dir: str | None = None  # debug: save each frame with OCR lines and block boxes drawn


class PipelineThread(QThread):
    blocks_ready = Signal(list)  # list[RenderBlock]
    status = Signal(str)

    def __init__(
        self,
        hwnd: int,
        engine: OcrEngine,
        service: TranslationService,
        config: PipelineConfig | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.hwnd = hwnd
        self.engine = engine
        self.service = service
        self.cfg = config or PipelineConfig()
        self.paused = False  # keep capturing, show nothing, translate nothing
        self.style_memory = StyleMemory()
        self.zone_style = ZoneStyle()  # subtitle mode: one size and colour for the zone
        self.frames = 0  # frames read with OCR
        self.skipped = 0  # frames the diff judged unchanged
        self.ocr_ms: deque[float] = deque(maxlen=2000)  # bounded: a long session must not grow memory
        self._stop = False
        self._reset = False
        self._tracker = BlockTracker(max_missing=self.cfg.max_missing)
        self._last_thumb: np.ndarray | None = None  # thumbnail of the region last read
        self._skip_run = 0

    def stop(self) -> None:
        self._stop = True

    def rescan(self) -> None:
        """Forget every tracked block on the next frame and read afresh."""
        self._reset = True

    # -- loop ----------------------------------------------------------------

    def run(self) -> None:
        cfg = self.cfg
        interval = int(1000 / cfg.fps) if cfg.fps else None
        try:
            with WgcWindowCapture(self.hwnd, min_interval_ms=interval) as cap:
                self.status.emit("capture started")
                was_paused = False
                while not self._stop:
                    frame = cap.next_frame(timeout=0.5)
                    if frame is None:
                        if cap.closed:
                            self.status.emit("capture closed: target window gone")
                            break
                        continue
                    if self._reset:
                        self._reset = False
                        self._forget_blocks(reset_style=True)
                    if self.paused:
                        if not was_paused:
                            self.blocks_ready.emit([])
                            was_paused = True
                        continue
                    if was_paused:
                        was_paused = False
                        self._forget_blocks(reset_style=False)
                    self.blocks_ready.emit(self._process(frame))
        except Exception as exc:  # surfaces in the UI instead of dying silently
            self.status.emit(f"pipeline error: {type(exc).__name__}: {exc}")
            raise

    def _forget_blocks(self, reset_style: bool) -> None:
        self._tracker = BlockTracker(max_missing=self.cfg.max_missing)
        self._last_thumb = None
        if reset_style:
            self.style_memory = StyleMemory()
            self.zone_style = ZoneStyle()
        self.blocks_ready.emit([])

    def _process(self, frame: Frame) -> list[RenderBlock]:
        """One frame: OCR and tracking (unless the frame is unchanged), then
        translations and what to draw."""
        cfg = self.cfg
        if self.unchanged(frame):
            self.skipped += 1
            blocks, lines = list(self._tracker.blocks), None
        else:
            t0 = time.perf_counter()
            blocks, lines = self.track_frame(frame)
            ocr_ms = (time.perf_counter() - t0) * 1000
            self.ocr_ms.append(ocr_ms)
            if cfg.debug:
                detail = " ".join(f"#{b.id}{b.bbox}{'*' if b.translation else ''}" for b in blocks)
                self.status.emit(
                    f"frame {self.frames}: ocr {ocr_ms:.0f}ms lines={len(lines)} blocks={len(blocks)} "
                    f"skipped={self.skipped} {detail}"
                )
            if cfg.dump_dir:
                self._dump(frame, lines, blocks)
        render = self.render_blocks(blocks, frame)
        if cfg.debug:
            render += [RenderBlock(bbox=b.bbox, outline=True) for b in blocks]
        return render

    # -- frame diff ------------------------------------------------------------

    def _area(self, frame: Frame) -> Box:
        """The part of the frame that is read: the client area, or all of it."""
        return self.cfg.area or (0, 0, frame.width, frame.height)

    def _thumbnail(self, frame: Frame) -> np.ndarray:
        x0, y0, x1, y1 = self.cfg.roi or self._area(frame)
        region = frame.image[y0:y1, x0:x1]
        if region.size == 0:
            return np.zeros((1, 1), dtype=np.uint8)
        grey = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        return cv2.resize(grey, None, fx=0.125, fy=0.125, interpolation=cv2.INTER_AREA)

    def unchanged(self, frame: Frame) -> bool:
        """True when the read region looks like the frame last read and no
        tracked block is waiting for another sighting (a new reading to
        confirm, a block not yet stable, or one that has just gone missing
        and must age out). Then OCR has nothing new to say and is skipped;
        translations that arrive meanwhile are still drawn."""
        cfg = self.cfg
        if cfg.diff_threshold <= 0:
            return False
        thumb = self._thumbnail(frame)
        last = self._last_thumb
        if (
            last is None
            or last.shape != thumb.shape
            or self._skip_run >= cfg.max_skipped
            or not self._settled()
            or float(np.mean(cv2.absdiff(last, thumb))) >= cfg.diff_threshold
        ):
            self._last_thumb, self._skip_run = thumb, 0
            return False
        self._skip_run += 1
        return True

    def _settled(self) -> bool:
        """No tracked block is waiting for another sighting."""
        cfg = self.cfg
        return all(
            b.pending_text is None and b.stable_frames >= cfg.stable_frames and b.missing_frames == 0
            for b in self._tracker.blocks
        )

    def track_frame(self, frame: Frame) -> tuple[list[TextBlock], list[TextLine]]:
        """OCR the frame and fold the lines into the tracked blocks. Returns
        the live blocks and the lines that were read."""
        self.frames += 1
        lines, scanned = self._ocr(frame)
        if self.cfg.line_filter:
            lines = self.cfg.line_filter.apply(lines)
        return self._tracker.update(lines, scanned), lines

    def render_blocks(self, blocks: list[TextBlock], frame: Frame) -> list[RenderBlock]:
        """Fill in the translations that are ready (queueing the rest) and
        return what the overlay should draw for them."""
        self._translate_ready(blocks, frame)
        area = self._area(frame)
        return [self._to_render(b, blocks, area) for b in blocks if b.translation is not None and self.is_subtitle(b)]

    # -- subtitle zone ------------------------------------------------------------

    @property
    def subtitle_mode(self) -> bool:
        return self.cfg.render == "subtitle" and self.cfg.roi is not None

    def _centered(self, block: TextBlock) -> bool:
        """The block's centre lies within the tolerance of the zone's centre."""
        assert self.cfg.roi is not None
        tolerance = self.cfg.subtitle_center_tolerance
        if tolerance <= 0:
            return True
        zx0, _, zx1, _ = self.cfg.roi
        offset = abs((block.bbox[0] + block.bbox[2]) / 2 - (zx0 + zx1) / 2)
        return offset <= tolerance * max(1, zx1 - zx0)

    def is_subtitle(self, block: TextBlock) -> bool:
        """In subtitle mode, whether a block looks like a subtitle rather than
        HUD text sharing the zone: centred, and about the learned size once
        that is known. Elsewhere every block counts."""
        if not self.subtitle_mode:
            return True
        if not self._centered(block):
            return False
        tolerance = self.cfg.subtitle_size_tolerance
        locked = self.zone_style.line_height
        if tolerance <= 0 or locked is None:
            return True
        return abs(line_height_of(block.bbox, len(block.line_texts)) - locked) <= tolerance * locked

    def _ocr_region(self, frame: Frame, box: Box) -> list[TextLine]:
        x0, y0, x1, y1 = box
        return self.engine.recognize(frame.image[y0:y1, x0:x1]).shifted(x0, y0).lines

    def _ocr(self, frame: Frame) -> tuple[list[TextLine], Box]:
        """OCR the roi (or the whole area), returning the lines and the
        region that was read."""
        full = self._area(frame)
        roi = self.cfg.roi
        if roi is None:
            return self._ocr_region(frame, full), full

        lines = self._ocr_region(frame, roi)
        every = self.cfg.full_scan_every
        if every and (self.frames - 1) % every == 0:  # the first frame, then every N-th
            others = self._ocr_region(frame, full)
            lines += [line for line in others if not intersects(line.bbox, roi)]
            return lines, full
        return lines, roi

    def _translate_ready(self, blocks: list[TextBlock], frame: Frame) -> None:
        """Fill in translations that are ready; queue the rest. Never blocks."""
        self.service.drain()
        misses: list[str] = []
        for block in blocks:
            needed = self.cfg.stable_frames
            if letter_count(block.text) < self.cfg.short_text_letters:
                needed = max(needed, self.cfg.short_text_frames)  # a fragment rarely survives a second look
            if block.stable_frames < needed or not self.is_subtitle(block):
                continue
            if block.translation is not None and not block.draft:
                continue  # final translation in place
            best = self.service.lookup_best(block.text)
            if best is None:
                misses.append(block.text)
                continue
            block.translation, is_final = best
            block.draft = not is_final
            if block.colors is None:
                self._sample_colors(block, frame)
            if not is_final:
                misses.append(block.text)  # keep the final request alive (resubmits after a cooldown)
        if misses:
            self.service.submit(misses)

    def _sample_colors(self, block: TextBlock, frame: Frame) -> None:
        sample = analyze_colors(frame.image, block.bbox)
        block.colors = (sample.bg, sample.fg)
        block.busy = sample.busy
        block.contrast = sample.contrast
        self.style_memory.observe(block.bbox, max(1, len(block.line_texts)), sample.bg, sample.fg, sample.busy)
        if self.subtitle_mode and self._centered(block):
            self.zone_style.observe(line_height_of(block.bbox, len(block.line_texts)), sample.fg)

    def _room(self, block: TextBlock, blocks: list[TextBlock], area: Box) -> tuple[int, int]:
        """Free pixels below and above a block before the next block that
        overlaps it horizontally, or the edge of the area."""
        _, ay0, _, ay1 = area
        x0, y0, x1, y1 = block.bbox
        below, above = ay1 - y1, y0 - ay0
        margin = self.cfg.grow_margin
        for other in blocks:
            if other is block:
                continue
            ox0, oy0, ox1, oy1 = other.bbox
            if ox1 <= x0 or ox0 >= x1:
                continue
            if oy0 >= y1:
                below = min(below, oy0 - y1 - margin)
            elif oy1 <= y0:
                above = min(above, y0 - oy1 - margin)
        return max(0, below), max(0, above)

    def _dump(self, frame: Frame, lines: list[TextLine], blocks: list[TextBlock]) -> None:
        dump_dir = self.cfg.dump_dir
        assert dump_dir  # only called when a dump folder is set
        os.makedirs(dump_dir, exist_ok=True)
        image = frame.image.copy()
        for line in lines:
            cv2.polylines(image, [line.quad.astype("int32").reshape(-1, 1, 2)], True, (0, 200, 255), 1)
        for block in blocks:
            x0, y0, x1, y1 = block.bbox
            color = (0, 255, 0) if block.translation else (0, 0, 255)
            cv2.rectangle(image, (x0, y0), (x1, y1), color, 2)
            cv2.putText(image, f"#{block.id}", (x0, max(10, y0 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        cv2.imwrite(os.path.join(dump_dir, f"frame_{self.frames:04d}.png"), image)

    def _to_render(self, block: TextBlock, blocks: list[TextBlock], area: Box) -> RenderBlock:
        assert block.translation is not None
        n_lines = max(1, len(block.line_texts))
        memory = self.style_memory
        # Lines that appear in the same place share one size, colour and style.
        bg, fg = memory.colors(block.bbox) or block.colors or ((0, 0, 0), (255, 255, 255))
        if self.subtitle_mode:
            cfg = self.cfg
            # One size and one colour for the whole zone, so lines never jump.
            font_px = cfg.subtitle_font_px or self.zone_style.font_px(memory.font_px(block.bbox, n_lines))
            text_rgb = cfg.subtitle_color or bgr_to_rgb(self.zone_style.fg or fg)
            return RenderBlock(
                bbox=block.bbox,
                lines=block.translation.split("\n"),
                bg=bgr_to_rgb(bg),
                fg=text_rgb,
                style="subtitle",
                source_lines=n_lines,
                font_px=font_px,
                zone=cfg.roi,
                position=cfg.subtitle_position,
                background=cfg.subtitle_background,
                pill_alpha=cfg.subtitle_pill_alpha,
                bold=cfg.subtitle_bold,
                hide_source=cfg.subtitle_hide_source,
            )
        # In-place mode: patch the original out in its own colours, or use a pill
        # where a flat patch would show (busy background, low contrast).
        style = self.cfg.style
        if style == "auto":
            busy = memory.busy(block.bbox, default=block.busy)
            style = "pill" if busy or block.contrast < 60 else "patch"
        below, above = self._room(block, blocks, area)
        return RenderBlock(
            bbox=block.bbox,
            lines=block.translation.split("\n"),
            bg=bgr_to_rgb(bg),
            fg=bgr_to_rgb(fg),
            style=style,
            source_lines=n_lines,
            font_px=memory.font_px(block.bbox, n_lines),
            room_below=below,
            room_above=above,
        )
