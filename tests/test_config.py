from __future__ import annotations

from pathlib import Path

from gametl.app.config import BOTTOM_STRIP, DEFAULT_HOTKEYS, NO_LETTERS_PATTERN, ProfileStore, Settings, slug


def test_settings_round_trip_and_unknown_keys_ignored() -> None:
    s = Settings(window_match="Fake Game", target_lang="tr", ignore_zones=["0,0,0.5,0.1"])
    data = s.to_dict()
    data["future_option"] = 42
    back = Settings.from_dict(data)
    assert back == s
    assert back.hotkeys == DEFAULT_HOTKEYS


def test_hotkeys_fill_in_defaults() -> None:
    s = Settings.from_dict({"hotkeys": {"toggle": "ctrl+alt+t"}})
    assert s.hotkeys["toggle"] == "ctrl+alt+t"
    assert s.hotkeys["pause"] == DEFAULT_HOTKEYS["pause"]
    assert s.hotkeys["select"] == "ctrl+shift+a"  # added later: older profiles get it too


def test_defaults_for_a_new_profile() -> None:
    s = Settings()
    assert (s.translator, s.source_lang, s.target_lang, s.draft) == ("deepl", "en", "tr", "")
    assert s.change_threshold == 20.0 and s.fps == 10.0


def test_the_bottom_strip_alone_is_the_default() -> None:
    assert Settings().full_scan_every == 0
    assert Settings().roi == BOTTOM_STRIP == "0,0.75,1,0.25"
    assert Settings().ignore_patterns == [NO_LETTERS_PATTERN]  # drops OCR phantoms such as a stray digit
    assert Settings().ocr_gpu is False


def test_subtitle_defaults_favour_a_steady_look() -> None:
    s = Settings()
    assert s.subtitle_position == "bottom" and s.subtitle_color == "" and s.subtitle_font_px == 0
    assert s.subtitle_hide_source is False  # the game's own line stays visible
    assert s.center_zone is False  # free selection; Shift centres
    assert (s.subtitle_center_tolerance, s.subtitle_size_tolerance) == (10, 35)
    assert s.short_line_confidence == 0.9
    # A profile saved before these fields existed keeps working and gets the defaults.
    old = Settings.from_dict({"window_match": "Alan Wake 2", "subtitle_position": "source", "center_zone": True})
    assert old.subtitle_position == "source" and old.center_zone is True
    assert old.subtitle_background == "pill" and old.subtitle_pill_alpha == 230


def test_saved_profiles_keep_their_own_patterns() -> None:
    assert Settings.from_dict({"ignore_patterns": []}).ignore_patterns == []


def test_effective_source_lang() -> None:
    assert Settings(lang="japan", source_lang="").effective_source_lang == "japan"  # empty follows the OCR language
    assert Settings(lang="japan", source_lang="ja").effective_source_lang == "ja"
    assert Settings(lang="japan").effective_source_lang == "en"  # the default source language


def test_slug() -> None:
    assert slug("Fake Game: The Sequel!") == "fake-game-the-sequel"
    assert slug("") == "game"
    assert slug("my_game v2") == "my-game-v2"


def test_slug_keeps_non_latin_titles_apart() -> None:
    assert slug("ゲーム") == "ゲーム"
    assert slug("Ведьмак 3") == "ведьмак-3"
    assert slug("Ölüm Oyunu") == "ölüm-oyunu"
    assert slug("ゲームA") != slug("ゲームB")
    assert slug("＋＋") == "game"  # symbols only: still the fallback


def test_profile_store_save_load_list_match_delete(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    assert store.list() == []
    assert store.last_profile is None

    store.save("Fake Game", Settings(window_match="Fake Game", game="Fake Game", target_lang="tr"))
    store.save("Other", Settings(window_match="Other Title", target_lang="de"))
    assert store.list() == ["fake-game", "other"]
    assert store.load("fake-game").target_lang == "tr"
    assert store.match_window("fake game - 1.2") == "fake-game"
    assert store.match_window("Something else") is None

    store.last_profile = "fake-game"
    assert store.last_profile == "fake-game"
    assert store.config_path.exists()

    store.delete("other")
    assert store.list() == ["fake-game"]
    assert store.cache_dir == tmp_path / "cache"
    assert store.models_dir == tmp_path / "models" and store.runtime_dir == tmp_path / "runtime"
