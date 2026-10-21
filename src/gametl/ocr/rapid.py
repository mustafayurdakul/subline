"""RapidOCR backend (PP-OCR detection + recognition on ONNX Runtime).

Model files download on first use into the rapidocr package directory.

Language/model notes (rapidocr 3.10 catalogue):
- PP-OCRv6 (default) ships one multilingual det + rec model per size
  (tiny / small / medium) covering Chinese, Traditional Chinese, English,
  Japanese (not tiny) and most Latin-script European languages.
- PP-OCRv5 has per-script mobile recognisers: korean, cyrillic, eslav,
  arabic, devanagari, th, el, latin, en, ch, plus a ch server model. Use
  version="PP-OCRv5" with size="mobile" for Korean or Cyrillic sources.
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
        log_level: str = "error",  # "warning" logs every frame with no text
        model_root_dir: str | None = None,  # where models download to; default: inside the package
    ) -> None:
        # Imported lazily: rapidocr pulls in onnxruntime + opencv at import time.
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import ModelType, OCRVersion

        params: dict[str, object] = {
            "Det.ocr_version": OCRVersion(version),
            "Rec.ocr_version": OCRVersion(version),
            "Det.model_type": ModelType(size),
            "Rec.model_type": ModelType(size),
            "Det.lang_type": lang,
            "Rec.lang_type": lang,
            # Standard PaddleOCR sizing: cap the long side, never upscale.
            # (rapidocr's default upscales short sides under 736 px, which makes
            # a wide subtitle strip several times more expensive.)
            "Det.limit_side_len": det_limit_side_len,
            "Det.limit_type": det_limit_type,
            # Text-direction classifier is for scanned documents; game text is upright.
            "Global.use_cls": use_cls,
            "Global.text_score": text_score,
            "Global.log_level": log_level,
            "EngineConfig.onnxruntime.use_dml": use_dml,
        }
        if threads is not None:
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = threads
        if model_root_dir:
            params["Global.model_root_dir"] = model_root_dir

        self.lang = lang
        self.version = version
        self.size = size
        self._ocr = RapidOCR(params=params)

    def warm_up(self, width: int = 1280, height: int = 720) -> float:
        """Load the models and run one frame-sized image so the first real call
        pays no allocation cost; returns milliseconds. The image carries a word
        so both detector and recogniser execute."""
        import cv2

        img = np.full((height, width, 3), 20, dtype=np.uint8)
        cv2.putText(img, "warm up", (width // 3, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3)
        t0 = time.perf_counter()
        self._ocr(img)
        return (time.perf_counter() - t0) * 1000.0

    def recognize(self, image_bgr: np.ndarray) -> OcrResult:
        t0 = time.perf_counter()
        out = self._ocr(image_bgr)
        total_ms = (time.perf_counter() - t0) * 1000.0

        lines: list[TextLine] = []
        boxes = getattr(out, "boxes", None)
        txts = getattr(out, "txts", None)
        scores = getattr(out, "scores", None)
        if boxes is not None and txts:
            for box, txt, score in zip(boxes, txts, scores):
                quad = np.asarray(box, dtype=np.float32).reshape(4, 2)
                lines.append(TextLine(text=str(txt), quad=quad, confidence=float(score)))

        timings = {"total": total_ms}
        elapse = getattr(out, "elapse_list", None) or []
        for key, value in zip(("det", "cls", "rec"), elapse):
            if isinstance(value, (int, float)):
                timings[key] = float(value) * 1000.0
        return OcrResult(lines=lines, timings_ms=timings)
