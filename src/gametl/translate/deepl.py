"""DeepL translation backend: fast (a few hundred ms), strong for European
languages including Turkish, free tier of 500k characters a month with an
API key from deepl.com. Usable as the main translator or as the draft tier
in front of Claude.

Key: handed in by the app (settings window, Credential Manager) or the
DEEPL_AUTH_KEY environment variable. Keys ending in ":fx" are free tier and
go to the free endpoint.
"""

from __future__ import annotations

import os
from typing import Any

from .base import TranslationError, TranslationRequest

FREE_URL = "https://api-free.deepl.com/v2/translate"
PRO_URL = "https://api.deepl.com/v2/translate"

# Our language codes (ISO or rapidocr names) -> DeepL codes.
# fmt: off
_CODES = {
    "en": "EN", "tr": "TR", "de": "DE", "fr": "FR", "es": "ES", "it": "IT", "pt": "PT", "pl": "PL",
    "nl": "NL", "ru": "RU", "uk": "UK", "cyrillic": "RU", "ar": "AR", "arabic": "AR", "ja": "JA",
    "japan": "JA", "ko": "KO", "korean": "KO", "zh": "ZH", "ch": "ZH", "chinese_cht": "ZH", "el": "EL",
    "id": "ID", "cs": "CS", "da": "DA", "fi": "FI", "hu": "HU", "nb": "NB", "no": "NB", "ro": "RO",
    "sk": "SK", "sl": "SL", "sv": "SV", "bg": "BG", "et": "ET", "lt": "LT", "lv": "LV", "vi": "VI",
}
# fmt: on
# DeepL no longer accepts the bare codes as targets: a variant must be named.
_TARGET_VARIANTS = {"EN": "EN-US", "PT": "PT-PT"}


def deepl_code(lang: str | None, target: bool = False) -> str | None:
    """Our code -> DeepL code. A code with a region ("en-GB") passes through
    upper-cased; as a `target`, plain English and Portuguese get a default
    variant since DeepL requires one there."""
    if not lang:
        return None
    code = lang.upper() if "-" in lang else _CODES.get(lang.lower(), lang[:2].upper())
    if target:
        code = _TARGET_VARIANTS.get(code, code)
    return code


class DeepLTranslator:
    name = "deepl"

    def __init__(self, auth_key: str | None = None, timeout: float = 15.0, session: Any = None) -> None:
        self.auth_key = auth_key or os.environ.get("DEEPL_AUTH_KEY") or ""
        if not self.auth_key:
            raise TranslationError("DeepL needs an API key: enter it in Settings > Translation")
        self.url = FREE_URL if self.auth_key.endswith(":fx") else PRO_URL
        self.timeout = timeout
        if session is None:
            import requests

            session = requests.Session()
        self._session = session
        self.calls = 0
        self.characters = 0

    def translate(self, request: TranslationRequest) -> list[str | None]:
        if not request.texts:
            return []
        body: dict[str, Any] = {
            "text": list(request.texts),
            "target_lang": deepl_code(request.target_lang, target=True),
            "preserve_formatting": True,
        }
        source = deepl_code(request.source_lang)
        if source:
            body["source_lang"] = source
        try:
            response = self._session.post(
                self.url,
                json=body,
                headers={"Authorization": f"DeepL-Auth-Key {self.auth_key}"},
                timeout=self.timeout,
            )
        except Exception as exc:  # network layer
            raise TranslationError(f"DeepL request failed: {exc}") from exc
        if response.status_code != 200:
            raise TranslationError(f"DeepL HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        translations = data.get("translations") or []
        if len(translations) != len(request.texts):
            raise TranslationError(f"DeepL returned {len(translations)} translations for {len(request.texts)} texts")
        self.calls += 1
        self.characters += sum(len(t) for t in request.texts)
        return [(t.get("text") or None) for t in translations]
