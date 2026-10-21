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
from ..layout.colors import bgr_to_rgb, sample_colors
from ..ocr.base import OcrEngine, TextLine
from ..overlay.window import RenderBlock
from ..tracking.blocks import BlockTracker, TextBlock, intersects
from ..translate.base import TranslationRequest, Translator

Box = tuple[int, int, int, int]


@dataclass(slots=True)
class PipelineConfig:
    area: Box | None = None  # frame pixels considered at all (e.g. the client area); None = whole frame
    roi: Box | None = None  # frame pixels; None = whole area every time
    fps: float = 10.0  # capture cap
    full_scan_every: int = 10  # with a roi: scan the whole frame every N frames
    stable_frames: int = 1  # confirming frames before translating
    max_missing: int = 3  # frames a block survives without being seen
    target_lang: str = "en"
    debug: bool = False  # also emit outlines of every tracked block
    dump_dir: str | None = None  # debug: save each frame with block boxes drawn


class PipelineThread(QThread):
    blocks_ready = Signal(list)  # list[RenderBlock]
    status = Signal(str)

    def __init__(
        self,
        hwnd: int,
        engine: OcrEngine,
        translator: Translator,
        config: PipelineConfig | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.hwnd = hwnd
        self.engine = engine
        self.translator = translator
        self.cfg = config or PipelineConfig()
        self._stop = False
        self.frames = 0
        self.ocr_ms: list[float] = []

    def stop(self) -> None:
        self._stop = True

    # -- loop ----------------------------------------------------------------

    def run(self) -> None:  # noqa: D401 (QThread override)
        cfg = self.cfg
        tracker = BlockTracker(max_missing=cfg.max_missing)
        interval = int(1000 / cfg.fps) if cfg.fps else None
        try:
            with WgcWindowCapture(self.hwnd, min_interval_ms=interval) as cap:
                self.status.emit("capture started")
                while not self._stop:
                    frame = cap.next_frame(timeout=0.5)
                    if frame is None:
                        if cap.closed:
                            self.status.emit("capture closed: target window gone")
                            break
                        continue
                    self.frames += 1
                    t0 = time.perf_counter()
                    lines, scanned = self._ocr(frame)
                    ocr_ms = (time.perf_counter() - t0) * 1000
                    self.ocr_ms.append(ocr_ms)

                    blocks = tracker.update(lines, scanned)
                    self._translate_ready(blocks, frame)

                    render = [self._to_render(b) for b in blocks if b.translation is not None]
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
        todo = [b for b in blocks if b.translation is None and b.stable_frames >= self.cfg.stable_frames]
        if not todo:
            return
        request = TranslationRequest(texts=[b.text for b in todo], target_lang=self.cfg.target_lang)
        results = self.translator.translate(request)
        for block, translated in zip(todo, results):
            block.translation = translated
            block.colors = sample_colors(frame.image, block.bbox)

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

    @staticmethod
    def _to_render(block: TextBlock) -> RenderBlock:
        bg, fg = block.colors or ((0, 0, 0), (255, 255, 255))
        assert block.translation is not None
        return RenderBlock(
            bbox=block.bbox,
            lines=block.translation.split("\n"),
            bg=bgr_to_rgb(bg),
            fg=bgr_to_rgb(fg),
            align="center",
        )
