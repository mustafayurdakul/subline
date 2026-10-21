"""Translators that do no real translation, for testing the pipeline and
the overlay without network or cost."""

from __future__ import annotations

from .base import TranslationRequest


class UppercaseTranslator:
    """Returns the source text in upper case: visibly different, same length,
    so layout and positioning can be judged."""

    name = "uppercase"

    def translate(self, request: TranslationRequest) -> list[str]:
        return [t.upper() for t in request.texts]


class EchoTranslator:
    """Returns the source text unchanged."""

    name = "echo"

    def translate(self, request: TranslationRequest) -> list[str]:
        return list(request.texts)
