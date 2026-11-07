"""Text helpers shared by tracking, the pipeline and translation."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_DIGITS = re.compile(r"\d+")
# A speaker name in front of a line, as games print it with speaker names on:
# one or two capitalised or upper-case words in any script (Casey, Dr.
# Darling, SAGA ANDERSON, Zoë, Ángel) and a colon, then the words spoken. The
# pattern takes words of letters; split_speaker checks the capitals. Never a
# lower-case word: "note: the door is locked" is a sentence, not a speaker.
_WORD = r"[^\W\d_](?:[^\W\d_]|['’.\-])*"
_NAME = rf"{_WORD}(?: {_WORD})?"
_SPEAKER = re.compile(rf"^\s*({_NAME})\s*[:：]\s+(\S.*)$", re.DOTALL)
# Or the name on a line of its own above the words, no colon (Alan Wake 2
# prints names that way): the words must then open like a sentence, a
# capital letter or a quote, so a line wrapped after its first word
# ("The\nfire escape...") is not read as a speaker; and the name must not end
# in a full stop, so a short sentence over the next ("Wait.\nDon't go.") is not.
_NAME_LINE = re.compile(rf"^\s*({_NAME})(?<!\.)[ \t]*\n\s*((?:[^\W\d_]|[\"“'‘(\[¿¡…]).*)$", re.DOTALL)
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


def single_line(text: str) -> str:
    """`text` with its line breaks and runs of spaces as single spaces.

    A block arrives with the line breaks of its OCR lines. A translator that
    splits at them translates a sentence wrapped over two lines as two
    fragments, which breaks the word order of a language like Turkish; the
    overlay wraps the translation to its own width anyway."""
    return " ".join(text.split())


def normalize_text(s: str) -> str:
    return single_line(s).casefold()


def letter_count(s: str) -> int:
    """Letters of any script in `s`; digits, punctuation and spaces do not count."""
    return sum(1 for ch in s if ch.isalpha())


def split_speaker(text: str) -> tuple[str, str]:
    """`text` as (speaker, words): the name before the colon, or alone on
    the line above the words with no colon, and the rest; ("", text) when no
    speaker is named. A line break after a colon counts as the space
    ("CASEY:\nGo." reads "CASEY: Go.")."""
    with_colon = _SPEAKER.match(text)
    match = with_colon or _NAME_LINE.match(text)
    if match is None:
        return "", text
    name, words = match.group(1), match.group(2)
    if not all(word[0].isupper() for word in name.split()) or name.split()[0].casefold() in _LEAD_INS:
        return "", text
    if with_colon is None and words[0].isalpha() and not words[0].isupper():
        return "", text  # no colon: the words must open like a sentence
    return name, words


def said_by(speaker: str, text: str) -> str:
    """`text` with its speaker in front ("Casey: Go."), the inverse of
    split_speaker; `text` alone when no speaker is named."""
    return f"{speaker}: {text}" if speaker else text


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
