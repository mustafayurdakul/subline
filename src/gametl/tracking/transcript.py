"""The chat transcript: the last lines of dialogue, each once, newest last.

Chat mode draws what was said as a chat log ("Casey: ...") instead of the
line on screen. The pipeline reports every tracked block that has a
translation, frame after frame; the transcript turns those sightings into
utterances. A block (one subtitle on screen) contributes one utterance,
which follows the block's text: a progressive reveal or a corrected OCR
reading replaces the utterance, the next line at the same spot (the
tracker reuses the block for it) is a new one. A line that was lost and
read again within a few seconds is the same utterance, not a second.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..textutil import normalize_text, text_similarity

REPEAT_SECONDS = 5.0  # the same text read again within this long is the line found again, not said again
SAME_LINE_RATIO = 0.8  # readings at least this alike are one line (an OCR fix, not the next line)


@dataclass(slots=True)
class Utterance:
    speaker: str  # "" when no speaker was named
    text: str  # the translation, as one line
    source: str  # the words read, to tell a correction from the next line
    block_id: int
    at: float  # when it was first seen, time.monotonic()


class Transcript:
    """The utterances kept for the chat card: at most `lines`, each dropped
    `seconds` after it arrived (0 = never). Speakers are numbered in the
    order they first speak, so each keeps its colour for the session."""

    def __init__(self, lines: int = 4, seconds: float = 20.0) -> None:
        self.lines = lines
        self.seconds = seconds
        self._utterances: list[Utterance] = []
        self._speaker_index: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._utterances)

    @property
    def utterances(self) -> list[Utterance]:
        return list(self._utterances)

    def speaker_index(self, speaker: str) -> int:
        """The speaker's number, counted from the first to speak; -1 for a line with no speaker."""
        if not speaker:
            return -1
        index = self._speaker_index.get(speaker)
        if index is None:
            index = self._speaker_index[speaker] = len(self._speaker_index)
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
            if _same_line(utterance.source, source):
                changed = (utterance.text, utterance.speaker) != (text, speaker)
                utterance.text, utterance.speaker, utterance.source = text, speaker, source  # a reveal or an OCR fix
                return changed
            break  # the block moved on to its next line
        for utterance in reversed(self._utterances):
            if now - utterance.at > REPEAT_SECONDS:
                break
            if _same_text(utterance.source, source):
                utterance.block_id = block_id  # the line was lost and found again: it goes on being this one
                return False
        self.speaker_index(speaker)
        self._utterances.append(Utterance(speaker, text, source, block_id, now))
        del self._utterances[: -self.lines]
        return True

    def prune(self, now: float) -> bool:
        """Drop the utterances older than `seconds`; True when any went."""
        if self.seconds <= 0:
            return False
        kept = [u for u in self._utterances if now - u.at <= self.seconds]
        changed = len(kept) != len(self._utterances)
        self._utterances = kept
        return changed

    def clear(self) -> None:
        self._utterances.clear()


def _same_text(a: str, b: str) -> bool:
    return normalize_text(a) == normalize_text(b)


def _same_line(known: str, reading: str) -> bool:
    """Whether `reading` is the line `known` again: the same text, the same
    text with more revealed (a typewriter effect), or an OCR correction."""
    known_n, reading_n = normalize_text(known), normalize_text(reading)
    if known_n == reading_n or reading_n.startswith(known_n) or known_n.startswith(reading_n):
        return True
    return text_similarity(known, reading) >= SAME_LINE_RATIO
