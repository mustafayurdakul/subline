"""Text comparison helpers shared by tracking and the translation cache."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")


def normalize_text(s: str) -> str:
    return _WS.sub(" ", s).strip().casefold()


def letter_count(s: str) -> int:
    """Letters of any script in `s`; digits, punctuation and spaces do not count."""
    return sum(1 for ch in s if ch.isalpha())


def text_similarity(a: str, b: str) -> float:
    """How likely two readings are the *same* on-screen text.

    1.0 when equal after whitespace/case normalisation. 0.0 when they are
    clearly different text: one empty; both contain numbers and the numbers
    differ (HUD counters, timers); or one extends the other by two or more
    characters (typewriter reveal). Otherwise a difflib ratio: OCR jitter
    between frames (l/1, O/0, a dropped full stop) scores above 0.9.
    """
    a, b = normalize_text(a), normalize_text(b)
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    digits_a, digits_b = _DIGITS.findall(a), _DIGITS.findall(b)
    if digits_a and digits_b and digits_a != digits_b:
        return 0.0
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if long_.startswith(short) and len(long_) - len(short) >= 2:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
