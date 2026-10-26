"""The settings window's backend: the map round-trips Settings, validates
before running, keeps keys out of profiles and maps key presses to hotkeys."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from gametl.app.config import DEFAULT_HOTKEYS, ProfileStore, Settings
from gametl.app.credentials import DEEPL_KEY, MemorySecretStore
from gametl.app.license import make_key
from gametl.app.settings_backend import (
    BOTTOM_STRIP,
    SettingsBackend,
    combo_from_key,
    invalid_hotkey,
    invalid_pattern,
)


def backend_for(tmp_path: Path, settings: Settings | None = None, secrets=None) -> SettingsBackend:
    return SettingsBackend(settings or Settings(), ProfileStore(tmp_path), secrets or MemorySecretStore())


def test_map_round_trips_settings(tmp_path: Path) -> None:
    original = Settings(
        window_match="Fake Game",
        game="Fake Game",
        roi="0,0.75,1,0.25",
        ignore_zones=["0,0,0.5,0.1"],
        ignore_patterns=[r"^\d+$"],
        lang="en",
        ocr_gpu=True,
        target_lang="tr",
        translator="uppercase",
        model="claude-sonnet-5-5",
        effort="medium",
        thinking="adaptive",
        structured=True,
        tone="casual",
        style="pill",
        render="inplace",
        subtitle_font_px=30,
        subtitle_color="#FFEE00",
        subtitle_background="shadow",
        subtitle_pill_alpha=120,
        subtitle_bold=True,
        subtitle_position="source",
        subtitle_hide_source=False,
        subtitle_center_tolerance=0,
        subtitle_size_tolerance=50,
        short_line_confidence=0.75,
        center_zone=True,
        font="Arial",
        fps=8.0,
        diff_threshold=2.5,
        hide_when_unfocused=False,
        exclude_from_capture=True,
        hotkeys={"toggle": "ctrl+alt+t"},
    )
    backend = backend_for(tmp_path, original)
    s = backend.settings
    assert s.value("ignore_patterns") == r"^\d+$"  # lists show one entry per line
    assert s.value("hotkey_toggle") == "ctrl+alt+t" and s.value("hotkey_pause") == DEFAULT_HOTKEYS["pause"]
    assert backend.to_settings() == Settings.from_dict(original.to_dict())


def test_fields_without_a_control_survive_and_qml_values_are_coerced(tmp_path: Path) -> None:
    loaded = Settings(window_match="Fake Game", stable_frames=3, max_missing=7, full_scan_every=5, debug=True)
    backend = backend_for(tmp_path, loaded)
    applied: list = []
    backend.applied.connect(lambda s, hwnd: applied.append((s, hwnd)))
    s = backend.settings
    s.insert("target_lang", "de")
    s.insert("fps", "24")  # a text field writes strings
    s.insert("subtitle_font_px", 28.0)  # a slider writes doubles
    s.insert("diff_threshold", "abc")  # nonsense keeps the value in force
    s.insert("ignore_patterns", "^\\d+$\n\n  (x)  \n")
    s.insert("subtitle_color", "   ")  # empty stays empty: the game's own colour
    s.insert("lang", "")  # an emptied field means the default
    backend.start()
    ((result, hwnd),) = applied
    assert hwnd is None
    assert result.target_lang == "de" and result.fps == 24.0 and result.subtitle_font_px == 28
    assert result.diff_threshold == 1.0 and result.subtitle_color == "" and result.lang == "en"
    assert result.ignore_patterns == ["^\\d+$", "(x)"]
    assert (result.stable_frames, result.max_missing, result.full_scan_every, result.debug) == (3, 7, 5, True)
    backend.saveProfile("kept")
    assert ProfileStore(tmp_path).load("kept").stable_frames == 3
    backend.load(Settings(stable_frames=1))  # loading other settings moves the base along
    assert backend.to_settings().stable_frames == 1


def test_invalid_pattern_or_hotkey_is_reported_and_blocks_start_and_save(tmp_path: Path) -> None:
    assert invalid_pattern(["^a$", r"\d+"]) is None
    problem = invalid_pattern(["^a$", "(unclosed"])
    assert problem is not None and "(unclosed" in problem
    assert invalid_hotkey(dict(DEFAULT_HOTKEYS)) is None
    backend = backend_for(tmp_path)
    applied: list = []
    backend.applied.connect(lambda s, hwnd: applied.append(s))
    backend.settings.insert("ignore_patterns", "^\\d+$\n(unclosed")
    backend.start()
    assert applied == [] and "(unclosed" in backend.problem
    backend.clearProblem()
    backend.saveProfile("x")
    assert "(unclosed" in backend.problem and ProfileStore(tmp_path).list() == []
    backend.settings.insert("ignore_patterns", "")
    backend.settings.insert("hotkey_toggle", "ctrl+")
    backend.clearProblem()
    backend.start()
    assert applied == [] and "Start / stop overlay" in backend.problem


def test_area_presets_and_window_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import gametl.capture.windows as windows

    monkeypatch.setattr(
        windows,
        "list_windows",
        lambda: [SimpleNamespace(title="Fake Game", hwnd=0x1234), SimpleNamespace(title="Editor", hwnd=0x99)],
    )
    backend = backend_for(tmp_path)
    assert backend.settings.value("roi") == ""
    backend.useBottomStrip()
    assert backend.settings.value("roi") == BOTTOM_STRIP == "0,0.75,1,0.25"
    backend.useWholeWindow()
    assert backend.settings.value("roi") == ""
    backend.refreshWindows()
    assert backend.windows == ["Editor", "Fake Game"]
    backend.settings.insert("window_match", "Fake Game")
    assert backend.selected_hwnd() == 0x1234  # the listed window's handle goes along with Start
    backend.settings.insert("window_match", "Fake")
    assert backend.selected_hwnd() is None  # a substring is matched by title instead
    backend.set("roi", "0.1,0.2,0.3,0.4")  # the tray, after a drag on screen
    assert backend.settings.value("roi") == "0.1,0.2,0.3,0.4"


def test_profiles_save_and_load(tmp_path: Path) -> None:
    backend = backend_for(tmp_path, Settings(window_match="Fake Game", game="Fake Game", translator="uppercase"))
    saved: list[str] = []
    loaded: list[str] = []
    backend.profile_saved.connect(saved.append)
    backend.profile_loaded.connect(lambda name, settings: loaded.append(name))
    backend.saveProfile("")  # no name: the game's
    assert saved == ["fake-game"] and backend.profileName == "fake-game"
    assert backend.profiles == ["fake-game"]
    store = ProfileStore(tmp_path)
    assert store.load("fake-game").translator == "uppercase" and store.last_profile == "fake-game"
    store.save("Other", Settings(window_match="Other", target_lang="de"))
    backend.profilesChanged.emit()
    backend.loadProfile("other")
    assert loaded == ["other"] and backend.profileName == "other"
    assert backend.settings.value("target_lang") == "de" and backend.to_settings().window_match == "Other"
    backend.loadProfile("missing")
    assert "missing" in backend.problem


def test_keys_go_to_the_secret_store_not_the_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # This machine may have real keys in its environment: hide them from the test.
    monkeypatch.delenv(DEEPL_KEY, raising=False)
    monkeypatch.setattr("gametl.app.credentials.user_environment_variable", lambda name: None)
    secrets = MemorySecretStore()
    backend = backend_for(tmp_path, secrets=secrets)
    assert backend.deeplKeyStatus == "not set"
    backend.saveKey(DEEPL_KEY, "  abc:fx ")
    assert secrets.get(DEEPL_KEY) == "abc:fx"
    assert backend.deeplKeyStatus == "set (memory)"
    assert "abc:fx" not in str(backend.to_settings().to_dict())
    backend.saveKey("SOMETHING_ELSE", "x")
    assert secrets.get("SOMETHING_ELSE") is None  # only the two known keys
    backend.clearKey(DEEPL_KEY)
    assert secrets.get(DEEPL_KEY) is None and backend.deeplKeyStatus == "not set"


def test_licence_activates_and_removes_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keypair: tuple[bytes, str]
) -> None:
    from datetime import date

    pem, public_hex = keypair
    monkeypatch.setattr("gametl.app.license.PUBLIC_KEY_HEX", public_hex)
    secrets = MemorySecretStore()
    backend = backend_for(tmp_path, secrets=secrets)
    assert backend.licenseText.startswith("trial: ")
    backend.activateLicense("GAMETL-nonsense.x")
    assert backend.licenseText.startswith("key rejected")
    backend.activateLicense(make_key(pem, "Ada Lovelace", "ada@example.com", date.today()))
    assert backend.licenseText == "licensed to Ada Lovelace"
    assert secrets.get("LICENSE_KEY").startswith("GAMETL-")
    backend.removeLicense()
    assert backend.licenseText.startswith("trial: ")


def test_remove_all_data_only_asks_the_owner(tmp_path: Path) -> None:
    backend = backend_for(tmp_path)
    assert str(tmp_path) in backend.dataDescription
    requests: list[int] = []
    backend.remove_all_data_requested.connect(lambda: requests.append(1))
    backend.removeAllData()  # the page confirmed already
    assert requests == [1] and tmp_path.exists()  # the backend deletes nothing: the tray does, then quits


def test_hotkey_edits_apply_at_once_but_not_while_loading(tmp_path: Path) -> None:
    backend = backend_for(tmp_path)
    changed: list[Settings] = []
    backend.hotkeys_changed.connect(changed.append)
    backend.load(Settings(hotkeys={"toggle": "alt+f5"}))
    assert changed == []
    backend.set("hotkey_pause", "ctrl+alt+p")  # as a page's write arrives
    assert (
        len(changed) == 1 and changed[0].hotkeys["pause"] == "ctrl+alt+p" and changed[0].hotkeys["toggle"] == "alt+f5"
    )
    backend.set("hotkey_pause", "")  # blank means the default
    assert changed[-1].hotkeys["pause"] == DEFAULT_HOTKEYS["pause"]
    backend.resetHotkeys()
    assert backend.to_settings().hotkeys == DEFAULT_HOTKEYS
    captures: list[bool] = []
    backend.hotkey_capture_changed.connect(captures.append)
    backend.setHotkeyCapture(True)
    backend.setHotkeyCapture(False)
    assert captures == [True, False]


def test_combo_from_key_press(tmp_path: Path) -> None:
    ctrl, shift, alt = (
        Qt.KeyboardModifier.ControlModifier,
        Qt.KeyboardModifier.ShiftModifier,
        Qt.KeyboardModifier.AltModifier,
    )
    # QML hands the slot plain ints; here the enums' values stand in for them.
    assert combo_from_key(Qt.Key.Key_T, (ctrl | shift).value) == "ctrl+shift+t"
    assert combo_from_key(Qt.Key.Key_F5, alt.value) == "alt+f5"
    assert combo_from_key(Qt.Key.Key_7, 0) == "7"
    assert combo_from_key(Qt.Key.Key_Space, ctrl.value) == "ctrl+space"
    assert combo_from_key(Qt.Key.Key_Return, Qt.KeyboardModifier.MetaModifier.value) == "win+enter"
    assert combo_from_key(Qt.Key.Key_Control, ctrl.value) == ""  # a modifier alone is not a hotkey
    assert combo_from_key(Qt.Key.Key_Udiaeresis, ctrl.value) == ""  # keys the registrar cannot name
    # Through the slot, as QML calls it.
    assert backend_for(tmp_path).comboFromKey(int(Qt.Key.Key_A), (ctrl | alt).value) == "ctrl+alt+a"


def test_named_keys_match_the_registrar() -> None:
    """Every key the press-to-set field can name is one the hotkey parser accepts."""
    from gametl.app.hotkeys import NAMED_KEYS
    from gametl.app.settings_backend import _NAMED_QT_KEYS

    assert set(_NAMED_QT_KEYS.values()) <= NAMED_KEYS.keys()


def test_status_and_text_for_the_header(tmp_path: Path) -> None:
    backend = backend_for(tmp_path)
    seen: list[str] = []
    backend.statusChanged.connect(lambda: seen.append(backend.status))
    backend.set_status(running=False, starting=True)
    backend.set_status(running=True)
    backend.set_status(running=True, paused=True)
    backend.set_status(running=True, paused=True)  # no change, no signal
    backend.set_status(running=False)
    assert seen == ["starting", "running", "paused", "idle"]
    backend.set_status_text("starting on 'Fake Game'...")
    assert backend.statusText == "starting on 'Fake Game'..."
    assert backend.appName == "Subline" and backend.version
