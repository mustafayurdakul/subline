"""The capture -> OCR -> track -> translate loop, on its own thread.

Emits a list of RenderBlocks for the overlay after every processed frame.
The UI thread never waits on OCR or translation.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from ..capture.base import Frame
from ..capture.wgc import WgcWindowCapture
from ..layout.colors import analyze_colors, bgr_to_rgb
from ..layout.style import StyleMemory
from ..ocr.base import OcrEngine, TextLine
from ..overlay.window import RenderBlock
from ..tracking.blocks import BlockTracker, TextBlock, intersects
from ..tracking.filters import LineFilter
from ..translate.service import TranslationService

Box = tuple[int, int, int, int]
RGB = tuple[int, int, int]


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
    subtitle_font_px: int = 0  # 0 = the median source line height
    subtitle_color: RGB = (255, 255, 255)
    subtitle_pill: bool = True
    subtitle_position: str = "source"
    subtitle_hide_source: bool = True
    grow_margin: int = 4  # px kept between a grown box and its neighbours
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
        self.frames = 0
        self.ocr_ms: deque[float] = deque(maxlen=2000)  # bounded: a long session must not grow memory
        self._stop = False
        self._reset = False
        self._tracker = BlockTracker(max_missing=self.cfg.max_missing)

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
        if reset_style:
            self.style_memory = StyleMemory()
        self.blocks_ready.emit([])

    def _process(self, frame: Frame) -> list[RenderBlock]:
        """OCR one frame, update the tracker, fill in translations, and
        return what the overlay should draw."""
        cfg = self.cfg
        self.frames += 1
        t0 = time.perf_counter()
        lines, scanned = self._ocr(frame)
        ocr_ms = (time.perf_counter() - t0) * 1000
        self.ocr_ms.append(ocr_ms)

        if cfg.line_filter:
            lines = cfg.line_filter.apply(lines)
        blocks = self._tracker.update(lines, scanned)
        self._translate_ready(blocks, frame)

        area = cfg.area or (0, 0, frame.width, frame.height)
        render = [self._to_render(b, blocks, area) for b in blocks if b.translation is not None]
        if cfg.debug:
            render += [RenderBlock(bbox=b.bbox, outline=True) for b in blocks]
            detail = " ".join(f"#{b.id}{b.bbox}{'*' if b.translation else ''}" for b in blocks)
            self.status.emit(
                f"frame {self.frames}: ocr {ocr_ms:.0f}ms lines={len(lines)} blocks={len(blocks)} {detail}"
            )
        if cfg.dump_dir:
            self._dump(frame, lines, blocks)
        return render

    def _ocr_region(self, frame: Frame, box: Box) -> list[TextLine]:
        x0, y0, x1, y1 = box
        return self.engine.recognize(frame.image[y0:y1, x0:x1]).shifted(x0, y0).lines

    def _ocr(self, frame: Frame) -> tuple[list[TextLine], Box]:
        """OCR the roi (or the whole area), returning the lines and the
        region that was read."""
        full = self.cfg.area or (0, 0, frame.width, frame.height)
        roi = self.cfg.roi
        if roi is None:
            return self._ocr_region(frame, full), full

        lines = self._ocr_region(frame, roi)
        every = self.cfg.full_scan_every
        if every and self.frames % every == 1:
            others = self._ocr_region(frame, full)
            lines += [line for line in others if not intersects(line.bbox, roi)]
            return lines, full
        return lines, roi

    def _translate_ready(self, blocks: list[TextBlock], frame: Frame) -> None:
        """Fill in translations that are ready; queue the rest. Never blocks."""
        self.service.drain()
        misses: list[str] = []
        for block in blocks:
            if block.stable_frames < self.cfg.stable_frames:
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
        import os

        import cv2

        dump_dir = self.cfg.dump_dir or "."
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
        if self.cfg.render == "subtitle" and self.cfg.roi is not None:
            return RenderBlock(
                bbox=block.bbox,
                lines=block.translation.split("\n"),
                bg=bgr_to_rgb(bg),
                fg=self.cfg.subtitle_color,
                style="subtitle",
                source_lines=n_lines,
                font_px=self.cfg.subtitle_font_px or memory.font_px(block.bbox, n_lines),
                zone=self.cfg.roi,
                position=self.cfg.subtitle_position,
                pill=self.cfg.subtitle_pill,
                hide_source=self.cfg.subtitle_hide_source,
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
