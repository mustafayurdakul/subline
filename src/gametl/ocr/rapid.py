"""RapidOCR backend: PP-OCR detection and recognition on ONNX Runtime.

Models download on first use into `model_root_dir` (the app passes its data
folder; the default is inside the rapidocr package).

Model notes (rapidocr 3.10 catalogue):
- PP-OCRv6, the default, ships one multilingual detector and recogniser per
  size (tiny / small / medium) covering Chinese, Traditional Chinese,
  English, Japanese (not tiny) and most Latin-script European languages.
- PP-OCRv5 has per-script mobile recognisers (korean, cyrillic, arabic,
  devanagari, th, el, latin, ...). `model_params` picks one of these for a
  language the v6 recogniser does not read, behind the same v6 detector.
"""

from __future__ import annotations

import time

import numpy as np

from .base import OcrResult, TextLine


def model_params(lang: str, version: str = "PP-OCRv6", size: str = "small") -> dict[str, object]:
    """The detector and recogniser rapidocr loads for `lang`.

    The PP-OCRv6 models read Chinese, Japanese and the Latin-script
    languages; asked for Korean, Cyrillic or Arabic they refuse to load. For
    such a language the recogniser is the PP-OCRv5 mobile one for its script,
    and the detector stays the chosen one, asked for under Chinese: one
    multilingual model per version and size, which finds lines of any script."""
    # The model catalogue only: no inference engine is loaded here.
    from rapidocr.utils.model_resolver import route_to_model_key
    from rapidocr.utils.typings import ModelType, OCRVersion, TaskType

    def listed(task: TaskType, ocr_version: OCRVersion, model_type: ModelType) -> bool:
        try:
            return route_to_model_key(task, ocr_version, lang, model_type) is not None
        except ValueError:  # a language that model does not read
            return False

    det_version, det_type = OCRVersion(version), ModelType(size)
    rec_version, rec_type = det_version, det_type
    if not listed(TaskType.REC, rec_version, rec_type):
        rec_version, rec_type = OCRVersion.PPOCRV5, ModelType.MOBILE
    return {
        "Det.ocr_version": det_version,
        "Det.model_type": det_type,
        "Det.lang_type": lang if listed(TaskType.DET, det_version, det_type) else "ch",
        "Rec.ocr_version": rec_version,
        "Rec.model_type": rec_type,
        "Rec.lang_type": lang,
    }


class RapidOcrEngine:
    def __init__(
        self,
        lang: str = "en",
        version: str = "PP-OCRv6",
        size: str = "small",
        use_dml: bool = False,
        det_limit_side_len: int = 960,
        model_root_dir: str | None = None,
    ) -> None:
        # Imported here: rapidocr pulls in onnxruntime and OpenCV at import time.
        from rapidocr import RapidOCR

        params: dict[str, object] = {
            **model_params(lang, version, size),
            # Standard PaddleOCR sizing: cap the long side, never upscale. The
            # rapidocr default upscales short sides under 736 px, which makes a
            # wide subtitle strip several times more expensive.
            "Det.limit_side_len": det_limit_side_len,
            "Det.limit_type": "max",
            # The text-direction classifier is for scanned documents; game text is upright.
            "Global.use_cls": False,
            "Global.text_score": 0.5,
            "Global.log_level": "error",  # "warning" would log every frame without text
            "EngineConfig.onnxruntime.use_dml": use_dml,
        }
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
