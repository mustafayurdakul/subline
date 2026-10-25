"""Consistent styling across lines that appear in the same place.

A game draws its subtitles in one font size and colour, but each OCR box
is a different height (ascenders, descenders, punctuation) and each sample
of the colours differs a little, so per-block values make the translation
jump between sizes and shades from line to line. StyleMemory remembers what
was seen in a horizontal band of the frame and answers with medians, so
every line in the subtitle zone renders alike.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import median

Box = tuple[int, int, int, int]
BGR = tuple[int, int, int]


@dataclass(slots=True)
class StyleSample:
    line_height: float  # source box height per text line
    bg: BGR
    fg: BGR
    busy: bool


class StyleMemory:
    def __init__(self, band_px: int = 64, keep: int = 24, min_samples: int = 2) -> None:
        self.band_px = max(8, band_px)
        self.keep = keep
        self.min_samples = min_samples
        self._bands: dict[int, deque[StyleSample]] = {}

    def band(self, bbox: Box) -> int:
        return int(((bbox[1] + bbox[3]) / 2) // self.band_px)

    def _samples(self, bbox: Box) -> list[StyleSample]:
        b = self.band(bbox)
        out: list[StyleSample] = []
        for key in (b - 1, b, b + 1):  # a two-line block's centre may sit one band off
            out.extend(self._bands.get(key, ()))
        return out

    def observe(self, bbox: Box, n_lines: int, bg: BGR, fg: BGR, busy: bool) -> None:
        line_height = (bbox[3] - bbox[1]) / max(1, n_lines)
        band = self._bands.setdefault(self.band(bbox), deque(maxlen=self.keep))
        band.append(StyleSample(line_height, bg, fg, busy))

    def font_px(self, bbox: Box, n_lines: int, factor: float = 0.8) -> int:
        """Font pixel size for a block: the band's median line height when
        enough has been seen there, else the block's own."""
        samples = self._samples(bbox)
        if len(samples) >= self.min_samples:
            # History only: the current box's own height is the jitter being removed.
            line_height = median(s.line_height for s in samples)
        else:
            line_height = (bbox[3] - bbox[1]) / max(1, n_lines)
        return max(6, int(line_height * factor))

    def colors(self, bbox: Box) -> tuple[BGR, BGR] | None:
        samples = self._samples(bbox)
        if len(samples) < self.min_samples:
            return None
        bg = tuple(int(median(s.bg[i] for s in samples)) for i in range(3))
        fg = tuple(int(median(s.fg[i] for s in samples)) for i in range(3))
        return bg, fg  # type: ignore[return-value]

    def busy(self, bbox: Box, default: bool) -> bool:
        samples = self._samples(bbox)
        if len(samples) < self.min_samples:
            return default
        votes = sum(1 for s in samples if s.busy)
        return votes * 2 > len(samples)


class ZoneStyle:
    """One style for the whole subtitle zone, locked once enough has been
    seen.

    Per-band medians still wobble: a one-line box, a two-line box and a line
    with descenders measure differently, so the size would change from line
    to line. A subtitle zone has one font, so one line height and one text
    colour are learned from the first `lock_after` readings and then held.
    The lock moves only when the median of a full window of later readings
    drifts by more than `drift` (the game changed its subtitle size), never
    line by line.
    """

    def __init__(self, lock_after: int = 3, window: int = 20, drift: float = 0.15) -> None:
        self.lock_after = lock_after
        self.drift = drift
        self._heights: deque[float] = deque(maxlen=window)
        self._fgs: deque[BGR] = deque(maxlen=window)
        self.line_height: float | None = None  # the locked value
        self._fg: BGR | None = None

    @property
    def locked(self) -> bool:
        return self.line_height is not None

    def observe(self, line_height: float, fg: BGR) -> None:
        self._heights.append(line_height)
        self._fgs.append(fg)
        current = median(self._heights)
        if self.line_height is None:
            if len(self._heights) >= self.lock_after:
                self.line_height, self._fg = current, self._median_fg()
        elif (
            len(self._heights) == self._heights.maxlen
            and abs(current - self.line_height) > self.drift * self.line_height
        ):
            self.line_height, self._fg = current, self._median_fg()

    def _median_fg(self) -> BGR:
        return tuple(int(median(c[i] for c in self._fgs)) for i in range(3))  # type: ignore[return-value]

    def font_px(self, fallback: int, factor: float = 0.8) -> int:
        """Font size from the locked line height; before the lock, from the
        running median of what was seen, else `fallback`."""
        if self.line_height is not None:
            height = self.line_height
        elif self._heights:
            height = median(self._heights)
        else:
            return fallback
        return max(6, int(height * factor))

    @property
    def fg(self) -> BGR | None:
        """The locked text colour, else the median so far, else None."""
        if self._fg is not None:
            return self._fg
        return self._median_fg() if self._fgs else None
