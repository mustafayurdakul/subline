"""Text helpers shared by tracking, translation and the chat transcript."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
# A speaker name in front of a line, as games print it with speaker names on:
# one or two capitalised or upper-case words (Casey, Dr. Darling, SAGA
# ANDERSON) and a colon, then the words spoken. Never a lower-case word: "note:
# the door is locked" is a sentence, not a speaker.
_SPEAKER = re.compile(r"^\s*((?:[A-Z][A-Za-z'’.\-]*)(?: (?:[A-Z][A-Za-z'’.\-]*))?)\s*[:：]\s+(\S.*)$", re.DOTALL)
# Capitalised words a game writes before a colon that name no one: HUD and
# tutorial lead-ins, which stay in the text and are translated with it.
_LEAD_INS = frozenset(
    [
        "note",
        "notes",
        "warning",
        "caution",
        "objective",
        "objectives",
        "mission",
        "quest",
        "task",
        "goal",
        "hint",
        "tip",
        "tips",
        "press",
        "hold",
        "remember",
        "new",
        "chapter",
        "part",
        "level",
        "act",
        "day",
        "error",
        "loading",
        "tutorial",
        "controls",
        "reward",
        "unlocked",
    ]
)


def normalize_text(s: str) -> str:
    return _WS.sub(" ", s).strip().casefold()


def letter_count(s: str) -> int:
    """Letters of any script in `s`; digits, punctuation and spaces do not count."""
    return sum(1 for ch in s if ch.isalpha())


def split_speaker(text: str) -> tuple[str, str]:
    """`text` as (speaker, words): the name before the colon and the rest,
    or ("", text) when no speaker is named. A line break after the name
    counts as the space ("CASEY:\nGo." reads "CASEY: Go.")."""
    match = _SPEAKER.match(text)
    if match is None or match.group(1).split()[0].casefold() in _LEAD_INS:
        return "", text
    return match.group(1), match.group(2)


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
