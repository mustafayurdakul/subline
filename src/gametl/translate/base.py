"""Translator interface.

A translator turns a batch of source strings into target strings, in order.
Backends: Claude, DeepL, offline CTranslate2 models, and dummies for testing.
A backend may be slow, so the pipeline never calls one directly: it goes
through `service.py`, which runs batches on worker threads.
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
    # Who says each text ("" when unknown), one per text: a hint for the translator (register, gender,
    # pronouns), never part of the text to translate. None when no line named a speaker.
    speakers: list[str] | None = None


CONTEXT_LINES = 30  # recent (source, translation) pairs a translator is given: about a thousand tokens


def quiet(_line: str) -> None:
    """The progress callback that reports nothing."""


def speakers_or_none(speakers: list[str]) -> list[str] | None:
    """`speakers` for a TranslationRequest: None when nobody is named."""
    return speakers if any(speakers) else None


class TranslationError(RuntimeError):
    """A whole batch failed (network, API error, refusal, malformed output).
    `retry_after` is how many seconds the backend should be left alone (a
    rejected key, a used-up quota); 0 means the service's usual cooldown."""

    def __init__(self, message: str, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class Translator(Protocol):
    name: str

    def translate(self, request: TranslationRequest) -> list[str | None]:
        """One entry per input text, same order. None = this item could not be
        translated. Raises TranslationError when the whole batch failed."""
        ...


# Language codes (ISO 639-1) and rapidocr model names -> English names
# fmt: off
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "tr": "Turkish", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
    "pt": "Portuguese", "pl": "Polish", "nl": "Dutch", "ru": "Russian", "uk": "Ukrainian", "ar": "Arabic",
    "arabic": "Arabic", "ja": "Japanese", "japan": "Japanese", "ko": "Korean", "korean": "Korean", "zh": "Chinese",
    "ch": "Chinese", "chinese_cht": "Traditional Chinese", "th": "Thai", "el": "Greek", "vi": "Vietnamese",
    "id": "Indonesian", "hi": "Hindi", "cs": "Czech", "da": "Danish", "fi": "Finnish", "hu": "Hungarian",
    "nb": "Norwegian", "ro": "Romanian", "sk": "Slovak", "sl": "Slovenian", "sv": "Swedish", "bg": "Bulgarian",
    "et": "Estonian", "lt": "Lithuanian", "lv": "Latvian",
}
# fmt: on
# rapidocr models that read a script, not a language ("cyrillic": Russian,
# Ukrainian, Bulgarian, ...): no source language follows from them, so the
# translator is left to detect it.
MULTI_LANGUAGE_SCRIPTS = frozenset({"cyrillic", "latin", "devanagari"})
# rapidocr model names and other spellings -> ISO 639-1 codes
_CODE_ALIASES = {"japan": "ja", "korean": "ko", "ch": "zh", "chinese_cht": "zh", "arabic": "ar", "no": "nb"}
# English names -> codes, so a typed "German" reads as "de"
_NAME_CODES = {name.lower(): code for code, name in LANGUAGE_NAMES.items() if len(code) == 2}


def language_name(code_or_name: str | None) -> str | None:
    """The English name of a code or rapidocr model name; the value itself
    when unknown; None for no value or a script that covers several languages."""
    if not code_or_name or code_or_name.strip().lower() in MULTI_LANGUAGE_SCRIPTS:
        return None
    return LANGUAGE_NAMES.get(code_or_name.strip().lower(), code_or_name)


def language_code(code_or_name: str | None) -> str | None:
    """The ISO 639-1 code for a code ("de", "pt-BR"), a rapidocr model name
    ("japan") or an English name ("German"); an unknown value comes back
    lower-cased; None for no value or a script that covers several languages."""
    key = (code_or_name or "").strip().lower()
    if not key or key in MULTI_LANGUAGE_SCRIPTS:
        return None
    code = _NAME_CODES.get(key, key.split("-")[0])  # a region does not change the language
    return _CODE_ALIASES.get(code, code)
