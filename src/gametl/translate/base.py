"""Translator interface.

A translator turns a batch of source strings into target strings, in order.
Backends: dummy (M1), Claude (M2), offline NMT (M5). Callers batch several
blocks per call; a backend may be slow, so callers never invoke it on the UI
thread (see `service.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class TranslationRequest:
    texts: list[str]
    source_lang: str | None = None  # language code or name; None = let the model detect
    target_lang: str = "tr"
    context: list[tuple[str, str]] | None = None  # recent (source, translation) pairs, oldest first


class TranslationError(RuntimeError):
    """A whole batch failed (network, API error, refusal, malformed output)."""


class Translator(Protocol):
    name: str

    def translate(self, request: TranslationRequest) -> list[str | None]:
        """One entry per input text, same order. None = this item could not be
        translated. Raises TranslationError when the whole batch failed."""
        ...


LANGUAGE_NAMES: dict[str, str] = {
    # OCR language codes (rapidocr) and common ISO codes -> English names
    "en": "English",
    "tr": "Turkish",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
    "nl": "Dutch",
    "ru": "Russian",
    "uk": "Ukrainian",
    "cyrillic": "Russian",
    "ar": "Arabic",
    "arabic": "Arabic",
    "ja": "Japanese",
    "japan": "Japanese",
    "ko": "Korean",
    "korean": "Korean",
    "zh": "Chinese",
    "ch": "Chinese",
    "chinese_cht": "Traditional Chinese",
    "th": "Thai",
    "el": "Greek",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "hi": "Hindi",
    "devanagari": "Hindi",
}


def language_name(code_or_name: str | None) -> str | None:
    if not code_or_name:
        return None
    return LANGUAGE_NAMES.get(code_or_name.lower(), code_or_name)
