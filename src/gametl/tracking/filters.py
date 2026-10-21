"""Drop OCR lines the user never wants translated: lines inside ignore zones
(minimap, HUD corners) and lines matching text patterns (pure numbers,
timers, button prompts)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ocr.base import TextLine

Box = tuple[int, int, int, int]


@dataclass(slots=True)
class LineFilter:
    zones: list[Box] = field(default_factory=list)  # frame pixels
    patterns: list[re.Pattern[str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.zones or self.patterns)

    @staticmethod
    def compile(zones: list[Box] | None = None, patterns: list[str] | None = None) -> LineFilter:
        return LineFilter(
            zones=list(zones or []),
            patterns=[re.compile(p, re.IGNORECASE) for p in (patterns or [])],
        )

    def ignores(self, line: TextLine) -> bool:
        x0, y0, x1, y1 = line.bbox
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for zx0, zy0, zx1, zy1 in self.zones:
            if zx0 <= cx < zx1 and zy0 <= cy < zy1:
                return True
        return any(p.search(line.text) for p in self.patterns)

    def apply(self, lines: list[TextLine]) -> list[TextLine]:
        if not self:
            return lines
        return [ln for ln in lines if not self.ignores(ln)]
