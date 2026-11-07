"""Translation cache with three tiers, persisted as JSON per game:

1. exact match on normalised text;
2. numeric reuse: the same text with different numbers (HUD counters,
   timers, prices) reuses the cached translation with the numbers swapped,
   so a ticking timer costs no requests;
3. fuzzy match against the most recently stored entries (OCR noise).
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import deque
from pathlib import Path

from ..jsonfile import write_text_atomic
from ..textutil import normalize_text, text_similarity

_DIGITS = re.compile(r"\d+")
# A suffix written onto a number ("5'te"): in Turkish it follows how the
# number is pronounced, so it is wrong once another number takes its place.
_NUMBER_SUFFIX = re.compile(r"\d+['\u2019]\w")


def numeric_template(key: str) -> tuple[str, list[str]]:
    """'hp 87/100 ammo 24' -> ('hp #/# ammo #', ['87', '100', '24'])."""
    numbers = _DIGITS.findall(key)
    return _DIGITS.sub("#", key), numbers


def substitute_numbers(translation: str, old: list[str], new: list[str]) -> str | None:
    """Swap the numbers of a cached translation for new ones, matching by value
    so reordering in the target language is fine. None when ambiguous: a
    duplicate value, a value that does not occur in the translation, or a
    suffix attached to a number ("5'te" would become "6'te", not "6'da")."""
    if len(old) != len(new) or len(set(old)) != len(old) or _NUMBER_SUFFIX.search(translation):
        return None
    found = _DIGITS.findall(translation)
    if sorted(found) != sorted(old):
        return None
    mapping = dict(zip(old, new, strict=True))
    return _DIGITS.sub(lambda m: mapping[m.group(0)], translation)


class TranslationCache:
    def __init__(
        self,
        path: Path | str | None = None,
        fuzzy_ratio: float = 0.92,
        fuzzy_min_len: int = 12,
        recent: int = 200,
    ) -> None:
        self.path = Path(path) if path else None
        self.fuzzy_ratio = fuzzy_ratio
        # Below this length one changed character is a different word as often
        # as an OCR slip ("Yes"/"Yet"), so short lines get exact matches only.
        self.fuzzy_min_len = fuzzy_min_len
        self._entries: dict[str, dict[str, str]] = {}  # key -> {target_lang: translation}
        self._templates: dict[tuple[str, str], tuple[list[str], str]] = {}  # (template, lang) -> (numbers, translation)
        self._recent: deque[str] = deque(maxlen=recent)
        self._lock = threading.Lock()
        self._dirty = False
        self.load_error: str | None = None  # set when the file on disk could not be read
        self.set_aside = False  # True when a damaged file was moved aside as .bad
        # The file's (mtime, size) when this cache last read or wrote it: a
        # change since then is another process's work, which a save keeps.
        self._disk_stamp: tuple[int, int] | None = None
        if self.path and self.path.exists():
            self._load()

    def _load(self) -> None:
        """Read the file at `path`. A damaged file must not stop the game
        from starting: it is set aside as .bad and the cache begins empty. A
        file that cannot be read at all (another program holds it, access is
        denied) is not damaged: it is left as it is, and this cache never
        saves over it (`path` becomes None)."""
        assert self.path is not None
        stamp = self._stamp()  # before reading: a write after it is merged on the next save
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            with self._lock:
                self._clear()
                for key, per_lang in data.get("entries", {}).items():
                    for lang, translation in per_lang.items():
                        self._store(key, lang, translation)
        except OSError as exc:
            self._load_failed(exc)
            self.path = None
        except (ValueError, AttributeError, TypeError) as exc:
            self._load_failed(exc)
            try:
                os.replace(self.path, self.path.with_suffix(self.path.suffix + ".bad"))
            except OSError:
                self.path = None  # still in place: a later session may read it, so it is not overwritten
            else:
                self.set_aside = True
        else:
            self._disk_stamp = stamp

    def _load_failed(self, exc: Exception) -> None:
        self.load_error = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._clear()

    def _stamp(self) -> tuple[int, int] | None:
        """The file's (mtime in ns, size), or None when it is not there."""
        assert self.path is not None
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def _clear(self) -> None:
        self._entries.clear()
        self._templates.clear()
        self._recent.clear()
        self._dirty = False

    @staticmethod
    def key(text: str) -> str:
        return normalize_text(text)

    def __len__(self) -> int:
        return len(self._entries)

    def has(self, text: str, target_lang: str) -> bool:
        """Whether a translation of exactly this text (after whitespace and
        case normalisation) is stored: no number swap, no fuzzy match."""
        key = self.key(text)
        with self._lock:
            return target_lang in self._entries.get(key, {})

    def get(self, text: str, target_lang: str) -> str | None:
        key = self.key(text)
        with self._lock:
            # 1. The same text, after whitespace and case normalisation.
            hit = self._entries.get(key, {}).get(target_lang)
            if hit is not None:
                return hit

            # 2. The same text with other numbers: swap them into the cached translation.
            template, numbers = numeric_template(key)
            if numbers:
                cached = self._templates.get((template, target_lang))
                if cached is not None:
                    swapped = substitute_numbers(cached[1], cached[0], numbers)
                    if swapped is not None:
                        return swapped

            # 3. A near-identical line seen recently (OCR noise such as l/1):
            #    long enough to tell noise from a different word, and the same
            #    number of words, so a dropped or added word never matches.
            if len(key) >= self.fuzzy_min_len:
                words = key.count(" ")
                for recent_key in reversed(self._recent):
                    if recent_key.count(" ") != words or not self._lengths_allow(key, recent_key):
                        continue
                    candidate = self._entries.get(recent_key, {}).get(target_lang)
                    if candidate is not None and text_similarity(key, recent_key) >= self.fuzzy_ratio:
                        return candidate
        return None

    def _lengths_allow(self, a: str, b: str) -> bool:
        """Whether two keys can be similar enough at all: the difflib ratio
        is at most 2 * min(len) / (len(a) + len(b)), so most of the recent
        keys are ruled out without comparing their characters."""
        return 2 * min(len(a), len(b)) >= self.fuzzy_ratio * (len(a) + len(b))

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

    def save(self) -> bool:
        """Write to disk if anything changed. Returns True when written.
        Lines another process wrote to the file since this cache read or
        wrote it (the pretranslate command, a second overlay) are kept."""
        if self.path is None:
            return False
        with self._lock:
            if not self._dirty:
                return False
        self._merge_from_disk()
        with self._lock:
            # Serialised under the lock: a worker thread may `put` while we write.
            text = json.dumps({"version": 1, "entries": self._entries}, ensure_ascii=False, indent=0)
            self._dirty = False
        try:
            write_text_atomic(self.path, text)
        except OSError:
            with self._lock:
                self._dirty = True  # still unsaved: the next save tries again
            raise
        self._disk_stamp = self._stamp()
        return True

    def _merge_from_disk(self) -> None:
        """Fold in the entries the file gained since this cache last read or
        wrote it; on a conflict this session's translation wins. They do not
        join the fuzzy tier's recent lines, which stay this session's own.
        Raises OSError when the changed file cannot be read, so that nothing
        is written over it."""
        assert self.path is not None
        stamp = self._stamp()
        if stamp is None or stamp == self._disk_stamp:
            return
        with open(self.path, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except ValueError:
                return  # damaged: nothing to keep
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return
        with self._lock:
            for key, per_lang in entries.items():
                if not isinstance(per_lang, dict):
                    continue
                for lang, translation in per_lang.items():
                    mine = self._entries.setdefault(key, {})
                    if lang in mine:
                        continue
                    mine[lang] = translation
                    template, numbers = numeric_template(key)
                    if numbers:
                        self._templates.setdefault((template, lang), (numbers, translation))
