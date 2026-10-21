"""Translation cache with three tiers, persisted as JSON per game:

1. exact match on normalised text;
2. numeric reuse: the same text with different numbers (HUD counters,
   timers, prices) reuses the cached translation with the numbers swapped,
   so a ticking timer costs no requests;
3. fuzzy match against recently used entries (OCR noise).
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import deque
from pathlib import Path

from ..textutil import normalize_text, text_similarity

_DIGITS = re.compile(r"\d+")


def numeric_template(key: str) -> tuple[str, list[str]]:
    """'hp 87/100 ammo 24' -> ('hp #/# ammo #', ['87', '100', '24'])."""
    numbers = _DIGITS.findall(key)
    return _DIGITS.sub("#", key), numbers


def substitute_numbers(translation: str, old: list[str], new: list[str]) -> str | None:
    """Swap the numbers of a cached translation for new ones, matching by value
    so reordering in the target language is fine. None when ambiguous: a
    duplicate value, or a value that does not occur in the translation."""
    if len(old) != len(new) or len(set(old)) != len(old):
        return None
    found = _DIGITS.findall(translation)
    if sorted(found) != sorted(old):
        return None
    mapping = dict(zip(old, new))
    return _DIGITS.sub(lambda m: mapping[m.group(0)], translation)


class TranslationCache:
    def __init__(self, path: Path | str | None = None, fuzzy_ratio: float = 0.92, recent: int = 200) -> None:
        self.path = Path(path) if path else None
        self.fuzzy_ratio = fuzzy_ratio
        self._entries: dict[str, dict[str, str]] = {}  # key -> {target_lang: translation}
        self._templates: dict[tuple[str, str], tuple[list[str], str]] = {}  # (template, lang) -> (numbers, translation)
        self._recent: deque[str] = deque(maxlen=recent)
        self._lock = threading.Lock()
        self._dirty = False
        if self.path and self.path.exists():
            self.load()

    @staticmethod
    def key(text: str) -> str:
        return normalize_text(text)

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, text: str, target_lang: str) -> str | None:
        key = self.key(text)
        with self._lock:
            hit = self._entries.get(key, {}).get(target_lang)
            if hit is not None:
                return hit

            template, numbers = numeric_template(key)
            if numbers:
                cached = self._templates.get((template, target_lang))
                if cached is not None:
                    swapped = substitute_numbers(cached[1], cached[0], numbers)
                    if swapped is not None:
                        return swapped

            for recent_key in reversed(self._recent):
                candidate = self._entries.get(recent_key, {}).get(target_lang)
                if candidate is not None and text_similarity(key, recent_key) >= self.fuzzy_ratio:
                    return candidate
        return None

    def put(self, text: str, target_lang: str, translation: str) -> None:
        key = self.key(text)
        if not key:
            return
        with self._lock:
            self._store(key, target_lang, translation)
            self._dirty = True

    def _store(self, key: str, target_lang: str, translation: str) -> None:
        self._entries.setdefault(key, {})[target_lang] = translation
        template, numbers = numeric_template(key)
        if numbers:
            self._templates[(template, target_lang)] = (numbers, translation)
        if key in self._recent:
            self._recent.remove(key)
        self._recent.append(key)

    def load(self) -> None:
        assert self.path is not None
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        with self._lock:
            self._entries.clear()
            self._templates.clear()
            self._recent.clear()
            for key, per_lang in data.get("entries", {}).items():
                for lang, translation in per_lang.items():
                    self._store(key, lang, translation)
            self._dirty = False

    def save(self) -> bool:
        """Write to disk if anything changed. Returns True when written."""
        if self.path is None:
            return False
        with self._lock:
            if not self._dirty:
                return False
            data = {"version": 1, "entries": self._entries}
            self._dirty = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=0)
        os.replace(tmp, self.path)
        return True
