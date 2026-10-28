"""DeepL translation backend: fast (a few hundred ms), strong for European
languages including Turkish, free tier of 500k characters a month with an
API key from deepl.com. Usable as the main translator or as the draft tier
in front of Claude.

Key: handed in by the app (settings window, Credential Manager) or the
DEEPL_AUTH_KEY environment variable. Keys ending in ":fx" are free tier and
go to the free endpoint.

Each request carries the recent source lines as DeepL's `context`: text it
reads but does not translate, so a name that was a person two lines ago
stays a person ("Hemingway", not the bird) and pronouns follow the scene.
"""

from __future__ import annotations

import os
from typing import Any

from .base import TranslationError, TranslationRequest, language_code, single_line

FREE_URL = "https://api-free.deepl.com/v2/translate"
PRO_URL = "https://api.deepl.com/v2/translate"

# The languages DeepL translates, by ISO 639-1 code; DeepL's code is the same, upper-cased.
# fmt: off
_DEEPL_LANGUAGES = frozenset({
    "ar", "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "hu", "id", "it", "ja", "ko", "lt", "lv", "nb",
    "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "tr", "uk", "vi", "zh",
})
# fmt: on
# Bare EN/PT/ZH are deprecated as targets: name a variant.
_TARGET_VARIANTS = {"EN": "EN-US", "PT": "PT-PT", "ZH": "ZH-HANS"}
# Statuses the player can act on, in plain words, and how many seconds to
# leave DeepL alone after each: retrying a rejected key or a used-up quota
# every few seconds only repeats the message.
_STATUS_ERRORS = {
    403: ("DeepL rejected the key: check it on the Translation page", 60.0),
    456: ("DeepL monthly quota used up", 60.0),
    429: ("DeepL is busy, retrying", 0.0),
}
CONTEXT_CHARS = 2000  # the most recent source lines that fit, newest last


def context_text(context: list[tuple[str, str]] | None) -> str:
    """The recent source lines (oldest first) as one text for DeepL's
    `context`, trimmed from the old end to CONTEXT_CHARS."""
    lines: list[str] = []
    size = 0
    for source, _translation in reversed(context or []):
        source = source.strip()
        if not source:
            continue
        if size + len(source) + 1 > CONTEXT_CHARS:
            break
        lines.append(source)
        size += len(source) + 1
    return "\n".join(reversed(lines))


def deepl_code(lang: str | None, target: bool = False) -> str | None:
    """Our code -> DeepL code; None lets DeepL detect the source language.

    A source is a bare language: a region ("en-GB") is dropped, since DeepL's
    `source_lang` takes none, and an unknown code or a script that covers
    several languages ("cyrillic") gives None. A `target` keeps a region the
    user chose, plain English, Portuguese and Chinese get a default variant,
    and an unknown target passes through upper-cased for DeepL to judge."""
    lang = (lang or "").strip()
    if not lang:
        return None
    if target and "-" in lang:
        return lang.upper()
    code = language_code(lang)
    if code not in _DEEPL_LANGUAGES:
        return lang.upper() if target else None
    code = code.upper()
    return _TARGET_VARIANTS.get(code, code) if target else code


class DeepLTranslator:
    name = "deepl"

    def __init__(self, auth_key: str | None = None, timeout: float = 15.0, session: Any = None) -> None:
        self.auth_key = auth_key or os.environ.get("DEEPL_AUTH_KEY") or ""
        if not self.auth_key:
            raise TranslationError("Add your DeepL key on the Translation page")
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
        # One paragraph per text: DeepL splits at line breaks by default, and
        # a subtitle wrapped over two lines is one sentence. The cache keeps the
        # original text; the overlay wraps the answer to its own width.
        texts = [single_line(t) for t in request.texts]
        body: dict[str, Any] = {
            "text": texts,
            "target_lang": deepl_code(request.target_lang, target=True),
            "preserve_formatting": True,
        }
        source = deepl_code(request.source_lang)
        if source:
            body["source_lang"] = source
        context = context_text(request.context)
        if context:
            body["context"] = context
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
            known = _STATUS_ERRORS.get(response.status_code)
            if known is not None:
                raise TranslationError(known[0], retry_after=known[1])
            raise TranslationError(f"DeepL HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        translations = data.get("translations") or []
        if len(translations) != len(request.texts):
            raise TranslationError(f"DeepL returned {len(translations)} translations for {len(request.texts)} texts")
        self.calls += 1
        self.characters += sum(len(t) for t in texts)
        return [(t.get("text") or None) for t in translations]
