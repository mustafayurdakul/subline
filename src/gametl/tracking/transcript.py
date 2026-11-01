"""The chat transcript: the last lines of dialogue, each once, newest last.

Chat mode draws what was said as a chat log ("Casey: ...") instead of the
line on screen. The pipeline reports every tracked block that has a
translation, frame after frame; the transcript turns those sightings into
utterances. A block (one subtitle on screen) contributes one utterance,
which follows the block's text: a progressive reveal or a corrected OCR
reading replaces the utterance, the next line at the same spot (the
tracker reuses the block for it) is a new one. A line that was lost and
read again within a few seconds is the same utterance, not a second. A
line leaves `seconds` after it was last on screen; one that stays on
screen (a dialogue choice) stays on the card.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from ..textutil import normalize_text

REPEAT_SECONDS = 5.0  # the same text read again this soon after it was last seen is the line found again
SAME_LINE_RATIO = 0.8  # readings at least this alike are one line (an OCR fix, not the next line)
NO_BLOCK = 0  # the tracker numbers blocks from 1: an utterance whose block was forgotten holds this


@dataclass(slots=True)
class Utterance:
    speaker: str  # "" when no speaker was named
    text: str  # the translation, as one line
    source: str  # the words read, to tell a correction from the next line
    block_id: int
    at: float  # when it was first seen, time.monotonic()
    seen: float  # when its block was last on screen


class Transcript:
    """The utterances kept for the chat card: at most `lines`, each dropped
    `seconds` after it was last seen (0 = never). Speakers are numbered in
    the order they first speak, so each keeps its colour for the session."""

    def __init__(self, lines: int = 4, seconds: float = 20.0) -> None:
        self.lines = lines
        self.seconds = seconds
        self._utterances: list[Utterance] = []
        self._speaker_index: dict[str, int] = {}
        # Block id -> the line last taken from it: a line that stays on screen after its utterance
        # aged out has had its time on the card and is not said again.
        self._taken: dict[int, str] = {}

    def __len__(self) -> int:
        return len(self._utterances)

    @property
    def utterances(self) -> list[Utterance]:
        return list(self._utterances)

    def speaker_index(self, speaker: str) -> int:
        """The speaker's number, counted from the first to speak, whatever
        the case OCR read the name in; -1 for a line with no speaker."""
        if not speaker:
            return -1
        key = speaker.casefold()
        index = self._speaker_index.get(key)
        if index is None:
            index = self._speaker_index[key] = len(self._speaker_index)
        return index

    def observe(self, block_id: int, speaker: str, source: str, text: str, now: float) -> bool:
        """A sighting of a block with its translation. Returns True when the
        transcript changed: a new utterance, or one replaced."""
        text = " ".join(text.split())
        if not text:
            return False
        for utterance in reversed(self._utterances):
            if utterance.block_id != block_id:
                continue
            if _same_line(utterance, speaker, source):
                changed = (utterance.text, utterance.speaker) != (text, speaker)
                utterance.text, utterance.speaker, utterance.source = text, speaker, source  # a reveal or an OCR fix
                utterance.seen = now
                self._taken[block_id] = source
                return changed
            break  # the block moved on to its next line
        for utterance in reversed(self._utterances):
            if now - utterance.seen <= REPEAT_SECONDS and _same_text(utterance, speaker, source):
                utterance.block_id, utterance.seen = block_id, now  # lost and found again: it goes on being this one
                self._taken[block_id] = source
                return False
        if _same_words(self._taken.get(block_id, ""), source):
            return False  # still on screen after its time on the card
        self.speaker_index(speaker)
        self._utterances.append(Utterance(speaker, text, source, block_id, now, now))
        self._taken[block_id] = source
        del self._utterances[: -self.lines]
        return True

    def prune(self, now: float) -> bool:
        """Drop the utterances not seen for `seconds`, and the oldest beyond
        `lines`; True when any went."""
        kept = self._utterances
        if self.seconds > 0:
            kept = [u for u in kept if now - u.seen <= self.seconds]
        kept = kept[-self.lines :] if self.lines > 0 else kept
        changed = len(kept) != len(self._utterances)
        self._utterances = kept
        return changed

    def forget_blocks(self) -> None:
        """The tracker starts afresh (a rescan, a changed area): its ids will
        be reused for other lines, so no utterance follows one any more. A
        line read again is found by its text."""
        for utterance in self._utterances:
            utterance.block_id = NO_BLOCK
        self._taken.clear()

    def clear(self) -> None:
        self._utterances.clear()
        self._taken.clear()


def _same_words(a: str, b: str) -> bool:
    return bool(a) and normalize_text(a) == normalize_text(b)


def _same_text(utterance: Utterance, speaker: str, source: str) -> bool:
    """The same words from the same speaker (a line without a speaker matches either way)."""
    if speaker and utterance.speaker and speaker.casefold() != utterance.speaker.casefold():
        return False
    return _same_words(utterance.source, source)


def _same_line(utterance: Utterance, speaker: str, reading: str) -> bool:
    """Whether `reading` is the utterance's line again: the same text, the
    same text with more revealed (a typewriter effect), or an OCR
    correction, from the same speaker. Another speaker's identical words
    are another line."""
    if speaker and utterance.speaker and speaker.casefold() != utterance.speaker.casefold():
        return False
    known, read = normalize_text(utterance.source), normalize_text(reading)
    if known == read or read.startswith(known) or known.startswith(read):
        return True
    # Compared over the shorter one's length: a reveal that went on after an
    # OCR slip in the earlier reading is still the same line.
    length = min(len(known), len(read))
    return SequenceMatcher(None, known[:length], read[:length]).ratio() >= SAME_LINE_RATIO
