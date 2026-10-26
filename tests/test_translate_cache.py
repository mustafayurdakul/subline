from __future__ import annotations

from pathlib import Path

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
