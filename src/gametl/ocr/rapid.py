"""RapidOCR backend: PP-OCR detection and recognition on ONNX Runtime.

Models download on first use into `model_root_dir` (the app passes its data
folder; the default is inside the rapidocr package).

Model notes (rapidocr 3.10 catalogue):
- PP-OCRv6, the default, ships one multilingual detector and recogniser per
  size (tiny / small / medium) covering Chinese, Traditional Chinese,
  English, Japanese (not tiny) and most Latin-script European languages.
- PP-OCRv5 has per-script mobile recognisers (korean, cyrillic, arabic,
  devanagari, th, el, latin, ...). Use version="PP-OCRv5" with size="mobile"
  for Korean or Cyrillic sources.
"""

from __future__ import annotations

import time

import numpy as np

from .base import OcrResult, TextLine


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(
        self,
        lang: str = "en",
        version: str = "PP-OCRv6",
        size: str = "small",
        use_cls: bool = False,
        use_dml: bool = False,
        text_score: float = 0.5,
        det_limit_side_len: int = 960,
        det_limit_type: str = "max",
        threads: int | None = None,
        log_level: str = "error",  # "warning" would log every frame without text
        model_root_dir: str | None = None,
    ) -> None:
        # Imported here: rapidocr pulls in onnxruntime and OpenCV at import time.
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import ModelType, OCRVersion

        params: dict[str, object] = {
            "Det.ocr_version": OCRVersion(version),
            "Rec.ocr_version": OCRVersion(version),
            "Det.model_type": ModelType(size),
            "Rec.model_type": ModelType(size),
            "Det.lang_type": lang,
            "Rec.lang_type": lang,
            # Standard PaddleOCR sizing: cap the long side, never upscale. The
            # rapidocr default upscales short sides under 736 px, which makes a
            # wide subtitle strip several times more expensive.
            "Det.limit_side_len": det_limit_side_len,
            "Det.limit_type": det_limit_type,
            # The text-direction classifier is for scanned documents; game text is upright.
            "Global.use_cls": use_cls,
            "Global.text_score": text_score,
            "Global.log_level": log_level,
            "EngineConfig.onnxruntime.use_dml": use_dml,
        }
        if threads is not None:
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = threads
        if model_root_dir:
            params["Global.model_root_dir"] = model_root_dir

        self._ocr = RapidOCR(params=params)

    def warm_up(self, width: int = 1280, height: int = 720) -> float:
        """Load the models and run one frame-sized image so the first real
        call pays no allocation cost. The image carries a word so both the
        detector and the recogniser execute. Returns milliseconds."""
        import cv2

        image = np.full((height, width, 3), 20, dtype=np.uint8)
        cv2.putText(image, "warm up", (width // 3, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3)
        t0 = time.perf_counter()
        self._ocr(image)
        return (time.perf_counter() - t0) * 1000.0

    def recognize(self, image_bgr: np.ndarray) -> OcrResult:
        t0 = time.perf_counter()
        out = self._ocr(image_bgr)
        total_ms = (time.perf_counter() - t0) * 1000.0

        lines: list[TextLine] = []
        if out.boxes is not None:  # None when nothing was detected
            for box, text, score in zip(out.boxes, out.txts or (), out.scores or (), strict=False):
                quad = np.asarray(box, dtype=np.float32).reshape(4, 2)
                lines.append(TextLine(text=str(text), quad=quad, confidence=float(score)))

        timings = {"total": total_ms}
        for stage, seconds in zip(("det", "cls", "rec"), out.elapse_list or [], strict=False):
            if isinstance(seconds, (int, float)):
                timings[stage] = float(seconds) * 1000.0
        return OcrResult(lines=lines, timings_ms=timings)
