from __future__ import annotations

import json
from pathlib import Path

import pytest

from gametl.app.config import (
    BOTTOM_STRIP,
    DEFAULT_HOTKEYS,
    NO_LETTERS_PATTERN,
    ProfileStore,
    Settings,
    slug,
    write_json_atomic,
)


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
    assert (s.translator, s.source_lang, s.target_lang, s.draft) == ("deepl", "", "tr", "")
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
    assert (s.font, s.subtitle_weight) == ("Segoe UI", "semibold")
    assert s.center_area is False  # free selection; Shift centres
    assert (s.subtitle_center_tolerance, s.subtitle_size_tolerance) == (10, 35)
    assert s.short_line_confidence == 0.9
    # A profile saved before these fields existed keeps working and gets the defaults.
    old = Settings.from_dict({"window_match": "Alan Wake 2", "subtitle_position": "source", "center_zone": True})
    assert old.subtitle_position == "source" and old.center_area is True  # center_zone: the name up to 0.1.8
    assert "center_zone" not in old.to_dict()
    assert old.subtitle_background == "pill" and old.subtitle_pill_alpha == 230
    # A 0.3.x profile in chat mode, with its screen-read hotkey: subtitle mode, the hotkey dropped.
    chat = Settings.from_dict({"render": "chat", "chat_lines": 6, "hotkeys": {"read": "ctrl+shift+d"}})
    assert chat.render == "subtitle" and "read" not in chat.hotkeys and chat.hotkeys == DEFAULT_HOTKEYS
    assert Settings.from_dict({"subtitle_bold": True}).subtitle_weight == "bold"  # the switch before weights
    assert Settings.from_dict({"subtitle_bold": False}).subtitle_weight == "semibold"
    assert Settings.from_dict({"font": "Fira Sans"}).font == "Segoe UI"  # a font 0.1.6 shipped and 0.1.8 does not
    assert Settings.from_dict({"font": "Arial", "subtitle_grain": 10}).font == "Arial"  # grain is dropped quietly


def test_saved_profiles_keep_their_own_patterns() -> None:
    assert Settings.from_dict({"ignore_patterns": []}).ignore_patterns == []


def test_effective_source_lang() -> None:
    assert Settings(lang="japan", source_lang="").effective_source_lang == "japan"  # empty follows the OCR language
    assert Settings(lang="japan", source_lang="ja").effective_source_lang == "ja"
    assert Settings(lang="japan").effective_source_lang == "japan"  # by default too


def test_the_old_default_source_language_gives_way_to_the_ocr_language() -> None:
    # Profiles up to 0.1.8 stored "en" whatever the OCR language was.
    assert Settings.from_dict({"lang": "japan", "source_lang": "en"}).effective_source_lang == "japan"
    assert Settings.from_dict({"lang": "en", "source_lang": "en"}).source_lang == "en"
    assert Settings.from_dict({"source_lang": "en"}).source_lang == "en"  # the OCR language defaults to en
    assert Settings.from_dict({"lang": "japan", "source_lang": "ja"}).source_lang == "ja"
    # Only stored profiles are upgraded: a value chosen now survives a copy.
    chosen = Settings(lang="ch", source_lang="en")
    assert chosen.copy().source_lang == "en" and chosen.copy() == chosen and chosen.copy() is not chosen


def test_choosing_an_area_leaves_the_sweep_alone() -> None:
    s = Settings(full_scan_every=30)
    s.set_area("0,0.5,1,0.5")
    assert (s.roi, s.full_scan_every) == ("0,0.5,1,0.5", 30)
    s.set_area("")
    assert (s.roi, s.full_scan_every) == ("", 30)


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
    assert store.last_profile == "fake-game"
    store.delete("Fake Game")  # the last profile used: forgotten with it
    assert store.list() == [] and store.last_profile is None
    assert store.cache_dir == tmp_path / "cache"
    assert store.models_dir == tmp_path / "models" and store.runtime_dir == tmp_path / "runtime"


def test_the_profile_of_an_open_game_or_the_last_one_is_remembered(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    assert store.remembered_profile(["Fake Game"]) is None  # nothing saved yet
    store.save("Fake Game", Settings(window_match="Fake Game", target_lang="de"))
    store.save("Other", Settings(window_match="Other Title"))
    assert store.remembered_profile(["Desktop", "Notepad"]) is None  # no game open, none used before

    name, settings, running = store.remembered_profile(["Notepad", "Fake Game v1.2"])
    assert (name, settings.target_lang, running) == ("fake-game", "de", True)

    store.last_profile = "other"
    name, _, running = store.remembered_profile(["Notepad"])
    assert (name, running) == ("other", False)  # not running: the last one, to start from the settings window
    # Both games open: the one played last wins.
    assert store.match_window("Fake Game", "Other Title") == "other"
    assert store.match_window("Fake Game", "Notepad") == "fake-game"

    store.last_profile = "gone"  # a profile deleted by hand
    assert store.remembered_profile(["Notepad"]) is None


def test_json_files_are_replaced_whole(tmp_path: Path) -> None:
    path = tmp_path / "profiles" / "game.json"
    write_json_atomic(path, {"a": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
    with pytest.raises(TypeError):
        write_json_atomic(path, {"a": object()})  # fails half-way through the dump
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}  # the old file is intact
    store = ProfileStore(tmp_path)
    store.save("game", Settings(target_lang="de"))
    store.save_config({"last_profile": "game"})
    assert store.load("game").target_lang == "de" and store.last_profile == "game"
    assert not list(tmp_path.rglob("*.tmp"))  # nothing left beside the files
