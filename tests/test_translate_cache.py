from __future__ import annotations

import json
from pathlib import Path

import pytest

import gametl.translate.cache as cache_module
from gametl.translate.cache import TranslationCache, substitute_numbers


def test_exact_hit_is_case_and_whitespace_insensitive() -> None:
    cache = TranslationCache()
    cache.put("Stay close, and keep your voice down.", "tr", "Yakın dur ve sesini alçak tut.")
    assert cache.get("stay close,  and keep your voice down.", "tr") == "Yakın dur ve sesini alçak tut."
    assert cache.get("Stay close, and keep your voice down.", "de") is None


def test_fuzzy_never_crosses_different_lines() -> None:
    cache = TranslationCache()
    cache.put("Go left at the bridge.", "tr", "left")
    assert cache.get("Go west at the bridge.", "tr") is None


def test_fuzzy_needs_a_long_line_and_the_same_word_count() -> None:
    cache = TranslationCache()
    cache.put("Yes, sir.", "tr", "Evet, efendim.")
    assert cache.get("Yet, sir.", "tr") is None  # short: one character is a different word
    cache.put("Stay close, and keep your voice down.", "tr", "X")
    assert cache.get("Stay close, and keep your voice down now.", "tr") is None  # an added word
    assert cache.get("Stay close, and keep your vo1ce down.", "tr") == "X"  # OCR slip, same words
    assert cache.get("Stay close, and keep your voice down", "tr") == "X"  # a dropped full stop


def test_damaged_cache_file_is_set_aside_and_the_cache_starts_empty(tmp_path: Path) -> None:
    path = tmp_path / "game.tr.json"
    path.write_text('{"version": 1, "entries": {"hello": ', encoding="utf-8")  # truncated
    cache = TranslationCache(path)
    assert len(cache) == 0
    assert cache.load_error is not None and "JSONDecodeError" in cache.load_error
    assert cache.set_aside
    assert not path.exists() and (tmp_path / "game.tr.json.bad").exists()
    cache.put("Hello", "tr", "Merhaba")
    assert cache.save() is True
    assert TranslationCache(path).get("Hello", "tr") == "Merhaba"

    path.write_text('{"version": 1, "entries": ["not", "a", "dict"]}', encoding="utf-8")  # wrong shape
    assert TranslationCache(path).load_error is not None


def test_numbers_are_swapped_into_a_cached_translation() -> None:
    cache = TranslationCache()
    cache.put("HP 87/100   Ammo 24   9s", "tr", "Can 87/100   Mühimmat 24   9sn")
    assert cache.get("HP 87/100 Ammo 24 8s", "tr") == "Can 87/100   Mühimmat 24   8sn"
    assert cache.get("HP 12/100 Ammo 3 41s", "tr") == "Can 12/100   Mühimmat 3   41sn"
    # reordered numbers in the target language are fine: matched by value
    cache.put("Level 3 of 10", "tr", "10 seviyeden 3.")
    assert cache.get("Level 7 of 10", "tr") == "10 seviyeden 7."


def test_numbers_not_swapped_when_ambiguous() -> None:
    cache = TranslationCache()
    cache.put("Wave 5 of 5", "tr", "Dalga 5 / 5")  # duplicate value: positions unknowable
    assert cache.get("Wave 4 of 5", "tr") is None
    cache.put("Chapter 2", "tr", "İkinci Bölüm")  # number spelled out in the translation
    assert cache.get("Chapter 3", "tr") is None
    cache.put("Gold 100", "tr", "Altın 100")
    assert cache.get("Gold", "tr") is None  # different template entirely
    # A Turkish suffix follows how the number is said: 5'te, but 6'da.
    cache.put("Meet me at 5", "tr", "Benimle 5'te buluş")
    assert cache.get("Meet me at 6", "tr") is None
    cache.put("Back at 9", "tr", "9\u2019da dönerim")  # with a typographic apostrophe too
    assert cache.get("Back at 5", "tr") is None


def test_substitute_numbers_helper() -> None:
    assert substitute_numbers("a 1 b 22", ["1", "22"], ["9", "8"]) == "a 9 b 8"
    assert substitute_numbers("a 1 b 22", ["1", "22"], ["9"]) is None
    assert substitute_numbers("a 1 b", ["1", "22"], ["9", "8"]) is None


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "game.tr.json"
    cache = TranslationCache(path)
    cache.put("Hello", "tr", "Merhaba")
    cache.put("Hello", "de", "Hallo")
    assert cache.save() is True
    assert cache.save() is False  # nothing new

    cache.put("Where were you when the lights went out?", "tr", "Işıklar söndüğünde neredeydin?")
    cache.save()

    again = TranslationCache(path)
    assert len(again) == 2
    assert again.get("hello", "tr") == "Merhaba"
    assert again.get("hello", "de") == "Hallo"
    # fuzzy works on loaded entries too (short words like "Hel1o" are rightly below the threshold)
    assert again.get("Where were you when the 1ights went out?", "tr") == "Işıklar söndüğünde neredeydin?"


def test_a_cache_file_that_cannot_be_read_is_never_written_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file another program holds is not damaged: it stays as it is, and
    this session's lines are not saved over the ones it holds."""
    path = tmp_path / "game.tr.json"
    stored = TranslationCache(path)
    stored.put("Hello", "tr", "Merhaba")
    stored.save()
    before = path.read_bytes()

    def locked(file, *args, **kwargs):
        if Path(file) == path:
            raise PermissionError(13, "The process cannot access the file")
        return open(file, *args, **kwargs)

    monkeypatch.setattr(cache_module, "open", locked, raising=False)
    cache = TranslationCache(path)
    assert cache.load_error is not None and "PermissionError" in cache.load_error
    assert not cache.set_aside and len(cache) == 0
    cache.put("Run!", "tr", "Koş!")
    assert cache.save() is False
    assert path.read_bytes() == before and not (tmp_path / "game.tr.json.bad").exists()
    monkeypatch.undo()

    # A damaged file that cannot be moved aside is not written over either.
    def held(*_args) -> None:
        raise PermissionError(13, "The process cannot access the file")

    path.write_text('{"entries": ', encoding="utf-8")
    monkeypatch.setattr(cache_module.os, "replace", held)
    cache = TranslationCache(path)
    assert cache.load_error is not None and not cache.set_aside
    cache.put("Run!", "tr", "Koş!")
    assert cache.save() is False
    assert path.read_text(encoding="utf-8") == '{"entries": '


def test_a_save_keeps_the_lines_another_process_wrote(tmp_path: Path) -> None:
    """The pretranslate command and a running overlay can share one file:
    neither save drops the other's lines, and on a conflict the saving side wins."""
    path = tmp_path / "game.tr.json"
    overlay = TranslationCache(path)
    script = TranslationCache(path)
    for i in range(30):
        script.put(f"Script line number {i}.", "tr", f"Senaryo satırı {i}.")
    script.put("Hello", "tr", "Selam")
    assert script.save() is True

    overlay.put("Hello", "tr", "Merhaba")
    assert overlay.save() is True
    on_disk = json.loads(path.read_text(encoding="utf-8"))["entries"]
    assert len(on_disk) == 31 and on_disk["hello"] == {"tr": "Merhaba"}
    assert overlay.get("Script line number 7.", "tr") == "Senaryo satırı 7."  # merged into memory too
    assert list(overlay._recent) == ["hello"]  # the fuzzy tier keeps this session's own lines

    script.put("Run!", "tr", "Koş!")
    assert script.save() is True
    on_disk = json.loads(path.read_text(encoding="utf-8"))["entries"]
    assert len(on_disk) == 32 and on_disk["hello"] == {"tr": "Selam"}  # this side's own answer wins on its save
    assert TranslationCache(path).get("Run!", "tr") == "Koş!"


def test_has_is_the_exact_tier_only() -> None:
    cache = TranslationCache()
    cache.put("I can't believe you actually did that.", "tr", "Bunu gerçekten yaptığına inanamıyorum.")
    cache.put("HP 87/100", "tr", "Can 87/100")
    assert cache.has("i can't believe  you actually did that.", "tr")
    assert not cache.has("I can't believe you actually did that!", "tr")  # fuzzy: get() answers, has() does not
    assert cache.get("I can't believe you actually did that!", "tr") is not None
    assert not cache.has("HP 12/100", "tr")  # by number swap only
    assert not cache.has("I can't believe you actually did that.", "de")


def test_a_failed_save_leaves_the_file_and_no_temporary_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import gametl.jsonfile as jsonfile

    path = tmp_path / "game.tr.json"
    cache = TranslationCache(path)
    cache.put("Hello", "tr", "Merhaba")
    cache.save()
    before = path.read_bytes()
    cache.put("Run!", "tr", "Koş!")

    def disk_full(*_args) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(jsonfile.os, "replace", disk_full)
    with pytest.raises(OSError):
        cache.save()
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["game.tr.json"]
    monkeypatch.undo()
    assert cache.save() is True  # still unsaved: the next save writes it
    assert TranslationCache(path).get("Run!", "tr") == "Koş!"
