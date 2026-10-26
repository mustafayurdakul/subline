"""Drop OCR lines the user never wants translated: lines inside ignore zones
(minimap, HUD corners), lines matching text patterns (pure numbers,
timers, button prompts), and one- or two-letter lines OCR is not sure
about (fragments of a word, HUD glyphs read as a letter)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..geometry import Box
from ..ocr.base import TextLine
from ..textutil import letter_count

# A line of this many letters or fewer is as often an OCR fragment or a HUD
# glyph as a word ("No.", "Go!"): it passes only when OCR is sure of it.
SHORT_LETTERS = 2


@dataclass(slots=True)
class LineFilter:
    zones: list[Box] = field(default_factory=list)  # frame pixels
    patterns: list[re.Pattern[str]] = field(default_factory=list)
    short_confidence: float = 0.9  # confidence a short line needs; 0 = off

    def __bool__(self) -> bool:
        return bool(self.zones or self.patterns or self.short_confidence > 0)

    @classmethod
    def compile(
        cls, zones: list[Box] | None = None, patterns: list[str] | None = None, short_confidence: float = 0.9
    ) -> LineFilter:
        return cls(
            zones=list(zones or []),
            patterns=[re.compile(p, re.IGNORECASE) for p in (patterns or [])],
            short_confidence=short_confidence,
        )

    def ignores(self, line: TextLine) -> bool:
        x0, y0, x1, y1 = line.bbox
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for zx0, zy0, zx1, zy1 in self.zones:
            if zx0 <= cx < zx1 and zy0 <= cy < zy1:
                return True
        if (
            self.short_confidence > 0
            and letter_count(line.text) <= SHORT_LETTERS
            and line.confidence < self.short_confidence
        ):
            return True
        return any(p.search(line.text) for p in self.patterns)

    def apply(self, lines: list[TextLine]) -> list[TextLine]:
        if not self:
            return lines
        return [ln for ln in lines if not self.ignores(ln)]
