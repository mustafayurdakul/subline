"""The capture -> OCR -> track -> translate loop, on its own thread.

Emits a list of RenderBlocks for the overlay after every processed frame.
The UI thread never waits on OCR or translation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from ..capture.base import Frame
from ..capture.wgc import WgcWindowCapture
from ..layout.colors import analyze_colors, bgr_to_rgb
from ..ocr.base import OcrEngine, TextLine
from ..overlay.window import RenderBlock
from ..tracking.blocks import BlockTracker, TextBlock, intersects
from ..tracking.filters import LineFilter
from ..translate.service import TranslationService

Box = tuple[int, int, int, int]


@dataclass(slots=True)
class PipelineConfig:
    area: Box | None = None  # frame pixels considered at all (e.g. the client area); None = whole frame
    roi: Box | None = None  # frame pixels; None = whole area every time
    fps: float = 10.0  # capture cap
    full_scan_every: int = 10  # with a roi: scan the whole frame every N frames
    stable_frames: int = 1  # confirming frames before translating
    max_missing: int = 3  # frames a block survives without being seen
    style: str = "auto"  # auto | patch | pill | outline; auto = patch unless the background is busy
    line_filter: LineFilter | None = None  # ignore zones and patterns
    grow_margin: int = 4  # px kept between a grown box and its neighbours
    debug: bool = False  # also emit outlines of every tracked block
    dump_dir: str | None = None  # debug: save each frame with block boxes drawn


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
        self._stop = False
        self.paused = False  # keep capturing, show nothing, translate nothing
        self._reset = False
        self.frames = 0
        self.ocr_ms: list[float] = []

    def stop(self) -> None:
        self._stop = True

    def rescan(self) -> None:
        """Forget every tracked block on the next frame and read afresh."""
        self._reset = True

    # -- loop ----------------------------------------------------------------

    def run(self) -> None:  # noqa: D401 (QThread override)
        cfg = self.cfg
        tracker = BlockTracker(max_missing=cfg.max_missing)
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
                        tracker = BlockTracker(max_missing=cfg.max_missing)
                        self.blocks_ready.emit([])
                    if self.paused:
                        if not was_paused:
                            self.blocks_ready.emit([])
                            was_paused = True
                        continue
                    if was_paused:
                        was_paused = False
                        tracker = BlockTracker(max_missing=cfg.max_missing)
                    self.frames += 1
                    t0 = time.perf_counter()
                    lines, scanned = self._ocr(frame)
                    ocr_ms = (time.perf_counter() - t0) * 1000
                    self.ocr_ms.append(ocr_ms)

                    if cfg.line_filter:
                        lines = cfg.line_filter.apply(lines)
                    blocks = tracker.update(lines, scanned)
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
                    self.blocks_ready.emit(render)
        except Exception as exc:  # surfaces in the UI instead of dying silently
            self.status.emit(f"pipeline error: {type(exc).__name__}: {exc}")
            raise

    def _ocr_region(self, frame: Frame, box: Box) -> list[TextLine]:
        x0, y0, x1, y1 = box
        return self.engine.recognize(frame.image[y0:y1, x0:x1]).shifted(x0, y0).lines

    def _ocr(self, frame: Frame) -> tuple[list[TextLine], Box]:
        full = self.cfg.area or (0, 0, frame.width, frame.height)
        roi = self.cfg.roi
        if roi is None:
            return self._ocr_region(frame, full), full

        lines = self._ocr_region(frame, roi)
        every = self.cfg.full_scan_every
        if every and self.frames % every == 1:
            others = self._ocr_region(frame, full)
            lines += [ln for ln in others if not intersects(ln.bbox, roi)]
            return lines, full
        return lines, roi

    def _translate_ready(self, blocks: list[TextBlock], frame: Frame) -> None:
        """Fill in translations that are ready; queue the rest. Never blocks."""
        self.service.drain()
        misses: list[str] = []
        for block in blocks:
            if block.translation is not None or block.stable_frames < self.cfg.stable_frames:
                continue
            translated = self.service.lookup(block.text)
            if translated is None:
                misses.append(block.text)
                continue
            block.translation = translated
            sample = analyze_colors(frame.image, block.bbox)
            block.colors = (sample.bg, sample.fg)
            block.extra["busy"] = sample.busy
            block.extra["contrast"] = sample.contrast
        if misses:
            self.service.submit(misses)

    def _room(self, block: TextBlock, blocks: list[TextBlock], area: Box) -> tuple[int, int]:
        """Free pixels below and above a block before the next block that
        overlaps it horizontally, or the edge of the area."""
        ax0, ay0, ax1, ay1 = area
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

        os.makedirs(self.cfg.dump_dir, exist_ok=True)  # type: ignore[arg-type]
        img = frame.image.copy()
        for ln in lines:
            cv2.polylines(img, [ln.quad.astype("int32").reshape(-1, 1, 2)], True, (0, 200, 255), 1)
        for b in blocks:
            x0, y0, x1, y1 = b.bbox
            cv2.rectangle(img, (x0, y0), (x1, y1), (0, 255, 0) if b.translation else (0, 0, 255), 2)
            cv2.putText(img, f"#{b.id}", (x0, max(10, y0 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        cv2.imwrite(os.path.join(self.cfg.dump_dir, f"frame_{self.frames:04d}.png"), img)  # type: ignore[arg-type]

    def _to_render(self, block: TextBlock, blocks: list[TextBlock], area: Box) -> RenderBlock:
        bg, fg = block.colors or ((0, 0, 0), (255, 255, 255))
        assert block.translation is not None
        style = self.cfg.style
        if style == "auto":
            busy = block.extra.get("busy", False)
            low_contrast = block.extra.get("contrast", 255.0) < 60
            style = "pill" if busy or low_contrast else "patch"
        below, above = self._room(block, blocks, area)
        return RenderBlock(
            bbox=block.bbox,
            lines=block.translation.split("\n"),
            bg=bgr_to_rgb(bg),
            fg=bgr_to_rgb(fg),
            align="center",
            style=style,
            source_lines=max(1, len(block.line_texts)),
            room_below=below,
            room_above=above,
        )
