"""Translator interface.

A translator turns a batch of source strings into target strings, in order.
Backends: dummy (M1), Claude (M2), offline NMT (M5). Callers batch several
blocks per call; a backend may be slow, so callers never invoke it on the UI
thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class TranslationRequest:
    texts: list[str]
    source_lang: str | None = None  # None = auto-detect
    target_lang: str = "en"
    context: list[str] | None = None  # recent lines, oldest first


class Translator(Protocol):
    name: str

    def translate(self, request: TranslationRequest) -> list[str]:
        """Return one translation per input text, same order and length."""
        ...
