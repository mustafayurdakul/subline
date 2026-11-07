"""The settings window's backend: the map round-trips Settings, validates
before running, keeps keys out of profiles and maps key presses to hotkeys."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from gametl.app.config import DEFAULT_HOTKEYS, ProfileStore, Settings
from gametl.app.credentials import DEEPL_KEY, MemorySecretStore
from gametl.app.settings_backend import (
    BOTTOM_STRIP,
    SettingsBackend,
    combo_from_key,
    invalid_hotkey,
    invalid_pattern,
    settings_problem,
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
        subtitle_weight="bold",
        subtitle_position="source",
        subtitle_hide_source=False,
        subtitle_center_tolerance=0,
        subtitle_size_tolerance=50,
        short_line_confidence=0.75,
        center_area=True,
        font="Arial",
        fps=8.0,
        change_threshold=30.0,
        hide_when_unfocused=False,
        exclude_from_capture=True,
        hotkeys={"toggle": "ctrl+alt+t"},
    )
    backend = backend_for(tmp_path, original)
    s = backend.settings
    assert s.value("ignore_patterns") == r"^\d+$"  # lists show one entry per line
    assert s.value("hotkey_toggle") == "ctrl+alt+t" and s.value("hotkey_pause") == DEFAULT_HOTKEYS["pause"]
    assert backend.to_settings() == Settings.from_dict(original.to_dict())


def test_untouched_fields_survive_and_qml_values_are_coerced(tmp_path: Path) -> None:
    # stable_frames and the like have controls but are not touched here; debug has no control at all.
    loaded = Settings(window_match="Fake Game", stable_frames=3, max_missing=7, full_scan_every=5, debug=True)
    backend = backend_for(tmp_path, loaded)
    started: list = []
    backend.start_requested.connect(lambda s, hwnd: started.append((s, hwnd)))
    s = backend.settings
    s.insert("target_lang", "de")
    s.insert("fps", "24")  # a text field writes strings
    s.insert("subtitle_font_px", 28.0)  # a slider writes doubles
    s.insert("change_threshold", "abc")  # nonsense keeps the value in force
    s.insert("ignore_patterns", "^\\d+$\n\n  (x)  \n")
    s.insert("subtitle_color", "   ")  # empty stays empty: the game's own colour
    s.insert("lang", "")  # an emptied field means the default
    s.insert("translator", "")
    backend.start()
    ((result, hwnd),) = started
    assert hwnd is None
    assert result.target_lang == "de" and result.fps == 24.0 and result.subtitle_font_px == 28
    assert result.change_threshold == 20.0 and result.subtitle_color == "" and result.lang == "en"
    assert result.translator == "deepl"
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
    started: list = []
    backend.start_requested.connect(lambda s, hwnd: started.append(s))
    backend.settings.insert("ignore_patterns", "^\\d+$\n(unclosed")
    backend.start()
    assert started == [] and "(unclosed" in backend.problem
    backend.clearProblem()
    assert backend.saveProfile("x") is False  # the popup stays open with the name
    assert "(unclosed" in backend.problem and ProfileStore(tmp_path).list() == []
    backend.settings.insert("ignore_patterns", "")
    backend.settings.insert("hotkey_toggle", "ctrl+")
    backend.clearProblem()
    backend.start()
    assert started == [] and "Start / stop overlay" in backend.problem
    backend.settings.insert("hotkey_toggle", "t")  # a hand-edited profile: a bare letter
    backend.clearProblem()
    backend.start()
    assert started == [] and "needs Ctrl, Alt or Win" in backend.problem


def test_an_area_or_zone_that_is_not_a_rectangle_is_refused(tmp_path: Path) -> None:
    """The overlay would refuse to start with it: the window says why at once, in the same words."""
    assert settings_problem(Settings()) is None and settings_problem(Settings(roi="")) is None
    assert settings_problem(Settings(roi="0,800,1920,280", ignore_zones=["0,0,0.2,0.2"])) is None  # pixels too
    for roi in ("0,0.75,1", "0;0.75;1;0.25", "0,0.75,1,0", "0,0.75,0,0.25"):
        assert (settings_problem(Settings(roi=roi)) or "").startswith(f"Area {roi!r}: "), roi
    problem = settings_problem(Settings(ignore_zones=["0,0,0.2,0.2", "minimap"]))
    assert problem is not None and "Ignore zone 'minimap'" in problem
    backend = backend_for(tmp_path)
    started: list = []
    backend.start_requested.connect(lambda s, hwnd: started.append(s))
    backend.settings.insert("roi", "0,0.75,1")
    backend.start()
    assert started == [] and "'0,0.75,1'" in backend.problem


def test_a_hotkey_needs_a_modifier_unless_no_program_types_its_key() -> None:
    """A global hotkey takes its key from every program: a letter, Tab or
    Enter alone, or with Shift only, would stop working everywhere."""
    for combo in ("t", "tab", "enter", "space", "shift+t", "shift+enter", "7"):
        assert "needs Ctrl, Alt or Win" in (invalid_hotkey({"toggle": combo}) or ""), combo
    for combo in ("ctrl+t", "alt+tab", "win+enter", "ctrl+shift+7", "f9", "shift+f12", "pause", "scrolllock"):
        assert invalid_hotkey({"toggle": combo}) is None, combo


def test_area_presets_and_window_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import gametl.capture.windows as windows

    monkeypatch.setattr(
        windows,
        "list_windows",
        lambda: [SimpleNamespace(title="Fake Game", hwnd=0x1234), SimpleNamespace(title="Editor", hwnd=0x99)],
    )
    backend = backend_for(tmp_path)
    assert backend.settings.value("roi") == BOTTOM_STRIP  # the default area
    backend.useWholeWindow()
    assert backend.settings.value("roi") == ""
    backend.useBottomStrip()
    assert backend.settings.value("roi") == BOTTOM_STRIP == "0,0.75,1,0.25"
    backend.refreshWindows()
    assert backend.windows == ["Editor", "Fake Game"]
    backend.settings.insert("window_match", "Fake Game")
    assert backend.selected_hwnd() == 0x1234  # the listed window's handle goes along with Start
    backend.settings.insert("window_match", "Fake")
    assert backend.selected_hwnd() is None  # a substring is matched by title instead
    backend.set("roi", "0.1,0.2,0.3,0.4")  # the tray, after a drag on screen
    assert backend.settings.value("roi") == "0.1,0.2,0.3,0.4"


def test_select_on_screen_refuses_settings_that_cannot_run(tmp_path: Path) -> None:
    """The tray takes the window's settings up for the selection and saves
    the area with them; only the area itself may be wrong, as it is replaced."""
    backend = backend_for(tmp_path)
    asked: list[int] = []
    backend.select_area_requested.connect(lambda: asked.append(1))
    backend.settings.insert("ignore_patterns", "(unclosed")
    backend.selectArea()
    assert asked == [] and "(unclosed" in backend.problem
    backend.settings.insert("ignore_patterns", "")
    backend.settings.insert("roi", "0,0.75,1")
    backend.clearProblem()
    backend.selectArea()
    assert asked == [1] and backend.problem == ""


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


def test_deleting_a_profile_forgets_it_everywhere(tmp_path: Path) -> None:
    backend = backend_for(tmp_path, Settings(window_match="Fake Game", target_lang="de"))
    backend.saveProfile("fake-game")
    backend.saveProfile("other")
    backend.loadProfile("fake-game")
    changes: list[None] = []
    backend.profilesChanged.connect(lambda: changes.append(None))
    backend.deleteProfile("other")  # not the one shown: the name in the header stays
    assert backend.profiles == ["fake-game"] and backend.profileName == "fake-game" and len(changes) == 1
    backend.deleteProfile("fake-game")
    store = ProfileStore(tmp_path)
    assert backend.profiles == [] and backend.profileName == "" and store.last_profile is None
    assert backend.to_settings().target_lang == "de"  # the settings shown stay; they are only no longer saved


def test_keys_go_to_the_secret_store_not_the_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # This machine may have real keys in its environment: hide them from the test.
    monkeypatch.delenv(DEEPL_KEY, raising=False)
    secrets = MemorySecretStore()
    backend = backend_for(tmp_path, secrets=secrets)
    assert backend.deeplKeyStatus == "not set" and not backend.deeplKeySet
    assert backend.saveKey(DEEPL_KEY, "  abc:fx ") is True  # the page blanks the field
    assert secrets.get(DEEPL_KEY) == "abc:fx"
    assert backend.deeplKeyStatus == "set (memory)" and backend.deeplKeySet
    assert "abc:fx" not in str(backend.to_settings().to_dict())
    assert backend.saveKey("SOMETHING_ELSE", "x") is False
    assert secrets.get("SOMETHING_ELSE") is None  # only the two known keys
    assert backend.saveKey(DEEPL_KEY, "   ") is False and secrets.get(DEEPL_KEY) == "abc:fx"
    backend.clearKey(DEEPL_KEY)
    assert secrets.get(DEEPL_KEY) is None and backend.deeplKeyStatus == "not set"


class RefusingStore(MemorySecretStore):
    """A credential store that refuses every change, as the Credential Manager does under some policies."""

    def set(self, name: str, value: str) -> None:
        raise OSError("vault refused")

    def delete(self, name: str) -> None:
        raise OSError("vault refused")


def test_a_store_that_refuses_shows_in_the_banner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Not only in the log: the key stays in its field and the profile popup stays open."""
    backend = backend_for(tmp_path, secrets=RefusingStore())
    assert backend.saveKey(DEEPL_KEY, "abc:fx") is False
    assert backend.problem == "Could not save the key: vault refused"
    backend.clearKey(DEEPL_KEY)
    assert backend.problem == "Could not remove the key: vault refused"

    def refuse(name: str, settings: Settings) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(backend.store, "save", refuse)
    assert backend.saveProfile("Fake Game") is False
    assert backend.problem == "Could not save profile fake-game: disk full" and backend.profileName == ""


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
    assert changed[-1].hotkeys == DEFAULT_HOTKEYS
    captures: list[bool] = []
    backend.hotkey_capture_changed.connect(captures.append)
    backend.setHotkeyCapture(True)
    backend.setHotkeyCapture(False)
    assert captures == [True, False]


def test_reset_registers_the_defaults_in_one_go(tmp_path: Path) -> None:
    """One at a time, two actions that had swapped combinations would clash
    halfway, and that failure would stay in the status line."""
    swapped = {**DEFAULT_HOTKEYS, "toggle": DEFAULT_HOTKEYS["select"], "select": DEFAULT_HOTKEYS["toggle"]}
    backend = backend_for(tmp_path, Settings(hotkeys=swapped))
    changed: list[Settings] = []
    backend.hotkeys_changed.connect(changed.append)
    backend.resetHotkeys()
    assert [s.hotkeys for s in changed] == [DEFAULT_HOTKEYS]


def test_a_combination_another_action_holds_is_named(tmp_path: Path) -> None:
    backend = backend_for(tmp_path)
    assert backend.hotkeyTaken("hotkey_toggle", DEFAULT_HOTKEYS["pause"]) == "Pause / resume"
    assert backend.hotkeyTaken("hotkey_toggle", "shift+ctrl+p") == "Pause / resume"  # the same keys in another order
    assert backend.hotkeyTaken("hotkey_toggle", DEFAULT_HOTKEYS["toggle"]) == ""  # its own
    assert backend.hotkeyTaken("hotkey_toggle", "ctrl+alt+f9") == ""
    backend.settings.insert("hotkey_pause", "")  # blank: the default, which is taken all the same
    assert backend.hotkeyTaken("hotkey_toggle", DEFAULT_HOTKEYS["pause"]) == "Pause / resume"
    backend.settings.insert("hotkey_pause", "ctrl+")  # a hand-edited profile: matches nothing
    assert backend.hotkeyTaken("hotkey_toggle", "ctrl+shift+p") == ""


def test_edits_go_out_once_the_typing_pauses_and_only_when_valid(qapp, tmp_path: Path) -> None:
    from tests.helpers import wait_until

    backend = backend_for(tmp_path)
    changed: list[Settings] = []
    backend.settings_changed.connect(changed.append)
    # set() is a page's write as the map reports it (the map's own signal is for QML writes only).
    backend.set("target_lang", "d")  # keystroke by keystroke
    backend.set("target_lang", "de")
    backend.set("roi", BOTTOM_STRIP)
    assert changed == []
    assert wait_until(lambda: bool(changed), tick=qapp.processEvents)
    assert len(changed) == 1 and changed[0].target_lang == "de" and changed[0].roi == BOTTOM_STRIP
    backend.set("ignore_patterns", "(unclosed")
    assert wait_until(lambda: bool(backend.problem), tick=qapp.processEvents)
    assert len(changed) == 1 and "(unclosed" in backend.problem  # a bad edit goes nowhere
    backend.set("ignore_patterns", "(closed)")
    assert wait_until(lambda: len(changed) == 2, tick=qapp.processEvents)
    assert backend.problem == "" and changed[1].ignore_patterns == ["(closed)"]  # corrected: banner gone
    backend.load(Settings(target_lang="fr"))  # loading is not an edit
    assert not wait_until(lambda: len(changed) > 2, timeout=0.8, tick=qapp.processEvents)


def test_start_takes_an_edit_still_waiting_to_go_out(qapp, tmp_path: Path) -> None:
    """Sent again once the pause is over, it would start the overlay twice."""
    from tests.helpers import wait_until

    backend = backend_for(tmp_path)
    changed: list[Settings] = []
    started: list[Settings] = []
    backend.settings_changed.connect(changed.append)
    backend.start_requested.connect(lambda s, hwnd: started.append(s))
    backend.set("window_match", "Typed Game")  # a field left by the click on Start
    backend.start()
    assert [s.window_match for s in started] == ["Typed Game"]
    assert not wait_until(lambda: bool(changed), timeout=0.8, tick=qapp.processEvents)


def test_loading_takes_down_the_problem_of_the_edit_it_replaces(qapp, tmp_path: Path) -> None:
    from tests.helpers import wait_until

    backend = backend_for(tmp_path)
    ProfileStore(tmp_path).save("other", Settings(window_match="Other"))
    backend.set("ignore_patterns", "(unclosed")
    assert wait_until(lambda: bool(backend.problem), tick=qapp.processEvents)
    backend.loadProfile("other")
    assert backend.problem == "" and backend.to_settings().window_match == "Other"
    backend.report_problem("no visible window matching 'Other'")  # the tray's, from a failed start
    backend.load(Settings())
    assert backend.problem == "no visible window matching 'Other'"  # not an edit's: it stays


def test_font_families_are_the_computers(qapp, tmp_path: Path) -> None:
    from PySide6.QtGui import QFontDatabase

    # The offscreen platform knows no fonts on Windows and fontconfig's on Linux.
    families = backend_for(tmp_path).fontFamilies
    assert families == [n for n in QFontDatabase.families() if not n.startswith("@")]
    assert not any(n.startswith("@") for n in families)


def test_the_preview_follows_every_edit(qapp, tmp_path: Path) -> None:
    from PySide6.QtCore import QSize

    from gametl.app.preview import PreviewImageProvider

    backend = backend_for(tmp_path)
    first = backend.previewStamp  # loading counts as a change too
    stamps: list[int] = []
    backend.previewChanged.connect(lambda: stamps.append(backend.previewStamp))
    backend.set("subtitle_weight", "bold")
    backend.set("subtitle_pill_alpha", 200)
    assert stamps == [first + 1, first + 2]
    size = QSize()
    image = PreviewImageProvider(backend).requestImage("2", size, QSize(680, 170))
    assert (image.width(), image.height()) == (680, 170) == (size.width(), size.height())
    assert any(image.pixelColor(x, 150).alpha() > 0 for x in range(0, 680, 4))  # the translation at the bottom
    assert any(image.pixelColor(x, 85).alpha() > 0 for x in range(0, 680, 4))  # the game's line in the middle


def test_the_preview_shows_size_and_hiding_as_in_a_1080p_game(qapp) -> None:
    from gametl.app.preview import preview_blocks, render_preview
    from gametl.overlay.paint import BlockPainter

    # Sizes are to scale (half of 1920 wide: half the pixels), not clamped to the area: 100 and 150 px differ.
    # Read from the blocks, not from painted rows: the offscreen platform on a CI runner may have no fonts.
    painter = BlockPainter()
    for game_px, shown_px in ((100, 50), (150, 75)):
        blocks = preview_blocks(Settings(subtitle_font_px=game_px), 960, 270, painter)
        assert [b.font_px for b in blocks] == [shown_px, shown_px]  # the game's line and the translation alike
    # The game's own line is drawn, so hiding it shows: the band covers it in the dark.
    shown = render_preview(Settings(subtitle_background="none", subtitle_hide_source=False), 960, 270)
    hidden = render_preview(Settings(subtitle_background="none", subtitle_hide_source=True), 960, 270)
    assert shown != hidden
    assert hidden.pixelColor(480, 135).alpha() > shown.pixelColor(480, 135).alpha()  # the band, opaque


def test_colour_swatch_shows_what_the_overlay_draws(tmp_path: Path) -> None:
    backend = backend_for(tmp_path)
    assert backend.colourHex("#ffee00") == "#FFEE00"
    assert backend.colourHex("10, 20, 300") == "#0A14FF"  # r,g,b is read too, clamped
    assert backend.colourHex("#ff") == "#FFFFFF"  # what does not parse is drawn white


def test_offline_download_can_run_again(qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The finished thread is dropped before it is deleted: `downloading`
    reads false afterwards and a second download starts."""
    from PySide6.QtCore import QCoreApplication, QEvent

    from tests.helpers import wait_until

    pairs: list[tuple[str, str]] = []

    def fake_ensure_offline(source, target, models_dir, runtime_dir, progress, cancelled):
        pairs.append((source, target))
        progress("fetching")
        return models_dir / f"argos-{source}_{target}" / "model"  # where an Argos package keeps model.bin

    monkeypatch.setattr("gametl.translate.offline.ensure_offline", fake_ensure_offline)

    def tick() -> None:
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)  # what the event loop does

    backend = backend_for(tmp_path, Settings(lang="japan", target_lang="tr", translator="offline"))
    backend.downloadOffline()
    assert backend.downloading
    assert wait_until(lambda: not backend.downloading, tick=tick)
    assert backend.downloadStatus == "Offline translation ready for ja → tr."  # the pair, as ISO codes
    backend.set("target_lang", "de")
    assert backend.downloadStatus == ""  # it spoke of the old pair
    backend.downloadOffline()
    assert wait_until(lambda: not backend.downloading, tick=tick)
    assert pairs == [("japan", "tr"), ("japan", "de")]
    backend.load(Settings(lang="en", target_lang="fr"))  # another profile: the line goes too
    assert backend.downloadStatus == ""


def test_closing_stops_a_download_in_progress(qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Quit and Remove all data wait for the thread: torn down while it
    runs, Qt aborts the process, and a download going on would write into
    the folder just wiped."""
    import threading
    import time

    from gametl.translate.offline import DownloadCancelled
    from tests.helpers import wait_until

    began, ended = threading.Event(), threading.Event()

    def fake_ensure_offline(source, target, models_dir, runtime_dir, progress, cancelled):
        began.set()
        try:
            while not cancelled():
                time.sleep(0.01)
            raise DownloadCancelled("download cancelled")
        finally:
            ended.set()

    monkeypatch.setattr("gametl.translate.offline.ensure_offline", fake_ensure_offline)
    backend = backend_for(tmp_path)
    backend.close()  # nothing to stop
    backend.downloadOffline()
    assert began.wait(5)
    backend.close()
    assert ended.is_set()  # returned only once the download had stopped
    assert wait_until(lambda: not backend.downloading, tick=qapp.processEvents)
    assert backend.downloadStatus == "Download cancelled."


def test_combo_from_key_press(tmp_path: Path) -> None:
    ctrl, shift, alt = (
        Qt.KeyboardModifier.ControlModifier,
        Qt.KeyboardModifier.ShiftModifier,
        Qt.KeyboardModifier.AltModifier,
    )
    # QML hands the slot plain ints; here the enums' values stand in for them.
    assert combo_from_key(Qt.Key.Key_T, (ctrl | shift).value) == "ctrl+shift+t"
    assert combo_from_key(Qt.Key.Key_F5, alt.value) == "alt+f5"
    assert combo_from_key(Qt.Key.Key_F5, 0) == "f5"  # no program types F5: it may stand alone
    assert combo_from_key(Qt.Key.Key_Pause, 0) == "pause"
    # Typing keys need Ctrl, Alt or Win: Tab or Enter alone would be bound globally.
    assert combo_from_key(Qt.Key.Key_7, 0) == ""
    assert combo_from_key(Qt.Key.Key_Tab, 0) == ""
    assert combo_from_key(Qt.Key.Key_Return, 0) == ""
    assert combo_from_key(Qt.Key.Key_T, shift.value) == ""
    assert combo_from_key(Qt.Key.Key_Space, ctrl.value) == "ctrl+space"
    assert combo_from_key(Qt.Key.Key_Return, Qt.KeyboardModifier.MetaModifier.value) == "win+enter"
    assert combo_from_key(Qt.Key.Key_Control, ctrl.value) == ""  # a modifier alone is not a hotkey
    assert combo_from_key(Qt.Key.Key_Udiaeresis, ctrl.value) == ""  # keys the registrar cannot name
    # A numpad digit is a key of its own: bound as the digit above the letters, it would never fire.
    assert combo_from_key(Qt.Key.Key_5, (ctrl | Qt.KeyboardModifier.KeypadModifier).value) == ""
    assert combo_from_key(Qt.Key.Key_5, ctrl.value) == "ctrl+5"
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


def test_the_pickers_list_what_the_app_accepts(tmp_path: Path) -> None:
    """The Advanced page's translator names are the ones a start accepts,
    and the Claude models are the ones with a known price, in that order."""
    from gametl.app.config import TRANSLATORS
    from gametl.translate.claude import PRICES_PER_MTOK

    backend = backend_for(tmp_path)
    assert backend.translators == list(TRANSLATORS) and backend.translators[0] == "deepl"
    assert backend.claudeModels == list(PRICES_PER_MTOK)
    assert backend.claudeModels == ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
