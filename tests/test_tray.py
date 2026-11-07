"""The tray app's glue, offscreen: which global hotkeys it holds and when, an
area selection that survives the settings window's echo and is saved alone,
a click on the icon, a failed start in the window's banner, Quit and "Remove
all data", and one tray app per data folder. The controller, the hotkey registry and the window are
stand-ins; the settings backend is real."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from gametl.app import tray as tray_module
from gametl.app.cleanup import CleanupReport
from gametl.app.config import DEFAULT_HOTKEYS, ProfileStore, Settings
from gametl.app.credentials import MemorySecretStore
from gametl.app.tray import SESSION_HOTKEYS, SingleInstance, TrayApp
from tests.helpers import wait_until


class FakeHotkeys:
    """Records what is held; `taken` combinations belong to another program."""

    taken: set[str] = set()

    def __init__(self) -> None:
        self.held: dict[str, str] = {}

    def register(self, name: str, combo: str, callback) -> bool:
        self.held.pop(name, None)
        if combo in self.taken:
            return False
        self.held[name] = combo
        return True

    def unregister_all(self) -> None:
        self.held.clear()


class FakeController(QObject):
    status = Signal(str)
    running_changed = Signal(bool)
    starting_changed = Signal(bool)
    paused_changed = Signal(bool)
    start_failed = Signal(str)
    area_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.secrets = MemorySecretStore()
        self.running = self.starting = self.paused = False
        self.applied: list[Settings] = []
        self.closed = 0

    def run(self, running: bool) -> None:
        self.running = running
        self.running_changed.emit(running)

    def apply(self, settings: Settings) -> None:
        self.applied.append(settings)

    def close(self) -> None:
        self.closed += 1

    def set_paused(self, paused: bool) -> None: ...
    def rescan(self) -> None: ...
    def clear_area(self) -> None: ...
    def toggle(self, settings: Settings) -> None: ...
    def select_area(self, settings: Settings) -> None: ...
    def start(self, settings: Settings, hwnd: int | None = None) -> None: ...
    def stop(self) -> None: ...


class FakeWindow:
    """The settings window without its QML pages."""

    def __init__(self, backend) -> None:
        self.backend = backend
        self.presented = 0
        self.visible = False

    def present(self) -> None:
        self.presented += 1
        self.visible = True

    def isVisible(self) -> bool:
        return self.visible

    def close(self) -> None:
        self.visible = False


class FakeApp:
    def __init__(self) -> None:
        self.quit_calls = 0

    def installNativeEventFilter(self, _filter) -> None: ...

    def quit(self) -> None:
        self.quit_calls += 1


@pytest.fixture
def tray(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    FakeHotkeys.taken = set()
    monkeypatch.setattr(tray_module, "GlobalHotkeys", FakeHotkeys)
    monkeypatch.setattr(tray_module, "SettingsWindow", FakeWindow)
    controller, store = FakeController(), ProfileStore(tmp_path / "data")
    app = TrayApp(FakeApp(), controller, store, Settings(full_scan_every=30))  # type: ignore[arg-type]
    yield app
    app.tray.hide()


def test_session_hotkeys_are_held_only_while_the_overlay_runs(tray: TrayApp) -> None:
    idle = {name: combo for name, combo in DEFAULT_HOTKEYS.items() if name not in SESSION_HOTKEYS}
    assert tray.hotkeys.held == idle  # idle: pause and rescan would only take keys from other programs
    tray.controller.run(True)
    assert tray.hotkeys.held == DEFAULT_HOTKEYS
    tray.controller.run(False)
    assert tray.hotkeys.held == idle


def test_no_hotkey_is_held_while_a_field_records_one(tray: TrayApp) -> None:
    tray._on_hotkey_capture(True)
    assert tray.hotkeys.held == {}
    tray.controller.run(True)  # the overlay starting meanwhile takes nothing back
    assert tray.hotkeys.held == {}
    tray._on_hotkey_capture(False)
    assert tray.hotkeys.held == DEFAULT_HOTKEYS


def test_a_combination_another_program_holds_is_reported(tray: TrayApp) -> None:
    FakeHotkeys.taken = {DEFAULT_HOTKEYS["toggle"]}
    tray.apply_hotkeys(tray.settings)
    assert "toggle" not in tray.hotkeys.held and "select" in tray.hotkeys.held
    assert tray._last_status == f"hotkeys not registered: toggle ({DEFAULT_HOTKEYS['toggle']})"


def test_an_area_selection_survives_the_windows_echo(qapp: QApplication, tray: TrayApp) -> None:
    tray.open_settings()
    tray.controller.area_selected.emit("0,0.6,1,0.3")
    assert (tray.settings.roi, tray.settings.full_scan_every) == ("0,0.6,1,0.3", 30)
    # The window took the area as an edit and sends its settings back once the typing pause is over.
    assert wait_until(lambda: bool(tray.controller.applied), timeout=3.0, tick=qapp.processEvents)
    echoed = tray.controller.applied[-1]
    assert (echoed.roi, echoed.full_scan_every) == ("0,0.6,1,0.3", 30)  # the sweep setting is left as it was
    assert (tray.settings.roi, tray.settings.full_scan_every) == ("0,0.6,1,0.3", 30)


def test_a_selected_area_is_saved_into_the_profile_alone(qapp: QApplication, tray: TrayApp) -> None:
    """Edits only being tried out reach the file when the profile is saved, not with an area."""
    tray.open_settings()
    assert tray.window is not None
    backend = tray.window.backend
    backend.set("target_lang", "tr")
    backend.saveProfile("Control")
    backend.set("target_lang", "de")  # tried out, not saved
    assert wait_until(lambda: tray.settings.target_lang == "de", timeout=3.0, tick=qapp.processEvents)
    tray.controller.area_selected.emit("0,0.6,1,0.3")
    saved = tray.store.load("control")
    assert (saved.roi, saved.target_lang) == ("0,0.6,1,0.3", "tr")
    assert tray.settings.target_lang == "de"  # still in force in this session


def test_a_single_click_opens_the_settings(tray: TrayApp) -> None:
    tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert tray.window is not None and tray.window.presented == 1
    tray._on_activated(QSystemTrayIcon.ActivationReason.Context)  # the right button shows the menu instead
    assert tray.window.presented == 1


def test_a_failed_start_shows_in_the_banner_until_the_next_start(tray: TrayApp) -> None:
    tray.controller.start_failed.emit("no visible window matching 'Fake Game'")  # before the window exists
    tray.open_settings()
    assert tray.window is not None
    backend = tray.window.backend
    assert backend.problem == "no visible window matching 'Fake Game'"
    tray.controller.starting_changed.emit(True)
    assert backend.problem == ""
    tray.controller.start_failed.emit("Add your DeepL key on the Translation page")
    assert backend.problem == "Add your DeepL key on the Translation page"
    backend.report_problem("invalid ignore pattern: (unclosed")  # an edit's problem is not the start's to clear
    tray.controller.starting_changed.emit(True)
    assert backend.problem == "invalid ignore pattern: (unclosed"


def test_a_deleted_profile_is_not_saved_again(tray: TrayApp) -> None:
    tray.open_settings()
    assert tray.window is not None
    backend = tray.window.backend
    backend.saveProfile("Control")
    assert tray.profile_name == "control"
    backend.deleteProfile("control")
    assert tray.profile_name is None
    tray.controller.area_selected.emit("0,0.6,1,0.3")  # an area selected afterwards
    assert not tray.store.exists("control")
    assert tray.settings.roi == "0,0.6,1,0.3"  # still taken up, only not saved


def test_remove_all_data_stops_once_wipes_and_quits(tray: TrayApp) -> None:
    tray.store.save("Fake Game", Settings(window_match="Fake Game"))
    tray.remove_all_data()
    assert tray.controller.closed == 1
    assert not tray.store.root.exists()
    assert tray.app.quit_calls == 1


def test_quitting_stops_a_download_before_the_overlay(tray: TrayApp, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all data deletes only once the download thread has ended."""
    tray.open_settings()
    assert tray.window is not None
    order: list[str] = []
    monkeypatch.setattr(tray.window.backend, "close", lambda: order.append("download"))
    monkeypatch.setattr(tray.controller, "close", lambda: order.append("overlay"))
    tray.quit()
    assert order == ["download", "overlay"] and tray.app.quit_calls == 1


@pytest.fixture
def left_behind(tray: TrayApp, monkeypatch: pytest.MonkeyPatch):
    """A wipe that leaves a loaded runtime library and a vault entry; the
    helper's start and the warning box are recorded, not run."""
    import gametl.app.main as main_module

    root = tray.store.root
    library = f"{root / 'runtime' / 'ctranslate2' / 'ctranslate2.dll'}: [WinError 5] Access is denied"
    entry = "Windows Credential Manager entry DEEPL_AUTH_KEY: refused"
    report = CleanupReport(failed=[library, entry])
    monkeypatch.setattr(tray_module, "remove_all_data", lambda store, secrets: report)
    monkeypatch.setattr(
        main_module, "finish_removal_command", lambda pid, data_dir: ["helper", str(pid), str(data_dir)], raising=False
    )
    started: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(tray_module.subprocess, "Popen", lambda command, **kwargs: started.append((command, kwargs)))
    warnings: list[str] = []
    monkeypatch.setattr(tray_module.QMessageBox, "warning", lambda parent, title, text: warnings.append(text))
    return SimpleNamespace(report=report, library=library, entry=entry, started=started, warnings=warnings)


def test_what_this_process_holds_is_removed_after_it_quits(tray: TrayApp, left_behind) -> None:
    """The offline runtime's libraries stay loaded until the process ends:
    a helper deletes the folder then, so only the rest is reported."""
    tray.remove_all_data()
    ((command, options),) = left_behind.started
    assert command == ["helper", str(os.getpid()), str(tray.store.root)]
    assert options["close_fds"] is True
    assert left_behind.warnings == ["Some data could not be removed:\n" + left_behind.entry]
    assert tray.app.quit_calls == 1
    left_behind.report.failed.remove(left_behind.entry)
    tray.remove_all_data()
    assert len(left_behind.warnings) == 1  # the folder alone: nothing to report


def test_a_helper_that_cannot_start_leaves_the_folder_in_the_report(
    tray: TrayApp, left_behind, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(command, **kwargs):
        raise OSError("cannot start")

    monkeypatch.setattr(tray_module.subprocess, "Popen", refuse)
    tray.remove_all_data()
    assert left_behind.warnings == [
        "Some data could not be removed:\n" + left_behind.library + "\n" + left_behind.entry
    ]


def test_a_second_tray_app_wakes_the_first_instead(qapp: QApplication, tmp_path: Path) -> None:
    first, second = SingleInstance(tmp_path), SingleInstance(tmp_path)
    woken: list[bool] = []
    try:
        assert first.claim(lambda: woken.append(True)) is True
        assert second.claim(lambda: pytest.fail("the second must not serve")) is False
        assert wait_until(lambda: woken == [True], timeout=3.0, tick=qapp.processEvents)
    finally:
        first.release()
    third = SingleInstance(tmp_path)  # the first has quit: the next one runs
    try:
        assert third.claim(lambda: None) is True
    finally:
        third.release()
    other = SingleInstance(tmp_path / "elsewhere")  # another data folder is another app
    try:
        assert other.claim(lambda: None) is True
    finally:
        other.release()
