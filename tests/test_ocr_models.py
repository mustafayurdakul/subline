"""Which OCR models load for each language the settings window offers,
checked against rapidocr's model catalogue: nothing is downloaded."""

from __future__ import annotations

import pytest
from rapidocr.inference_engine.base import FileInfo, InferSession
from rapidocr.utils.typings import EngineType, ModelType, OCRVersion, TaskType

from gametl.ocr.rapid import model_params


def ocr_langs() -> list[str]:
    from gametl.app.settings_backend import OCR_LANGS

    return list(OCR_LANGS)


@pytest.mark.parametrize("lang", ocr_langs())
def test_every_offered_language_has_a_detector_and_a_recogniser(lang: str) -> None:
    """The lookup rapidocr makes before it downloads a model: a language a
    model does not read raises ValueError here, and the session would fail
    to start."""
    params = model_params(lang)
    for task in ("Det", "Rec"):
        info = InferSession.get_model_url(
            FileInfo(
                engine_type=EngineType.ONNXRUNTIME,
                ocr_version=params[f"{task}.ocr_version"],
                task_type=TaskType(task.lower()),
                lang_type=params[f"{task}.lang_type"],
                model_type=params[f"{task}.model_type"],
            )
        )
        assert info["model_dir"].endswith(".onnx")


def test_languages_v6_does_not_read_get_a_v5_recogniser_behind_the_v6_detector() -> None:
    for lang in ("korean", "cyrillic", "arabic"):
        params = model_params(lang)
        assert (params["Det.ocr_version"], params["Det.model_type"]) == (OCRVersion.PPOCRV6, ModelType.SMALL)
        assert params["Det.lang_type"] == "ch"  # the one multilingual detector
        assert (params["Rec.ocr_version"], params["Rec.model_type"]) == (OCRVersion.PPOCRV5, ModelType.MOBILE)
        assert params["Rec.lang_type"] == lang
    params = model_params("japan")  # read by v6 itself: nothing changes
    assert params["Rec.ocr_version"] == OCRVersion.PPOCRV6 and params["Det.lang_type"] == "japan"
