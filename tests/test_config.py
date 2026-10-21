from __future__ import annotations

from pathlib import Path

from gametl.app.config import DEFAULT_HOTKEYS, ProfileStore, Settings, slug


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


def test_zone_only_is_the_default() -> None:
    assert Settings().full_scan_every == 0
    assert Settings().roi == ""


def test_effective_source_lang() -> None:
    assert Settings(lang="japan").effective_source_lang == "japan"
    assert Settings(lang="japan", source_lang="ja").effective_source_lang == "ja"


def test_slug() -> None:
    assert slug("Fake Game: The Sequel!") == "fake-game-the-sequel"
    assert slug("") == "game"


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
