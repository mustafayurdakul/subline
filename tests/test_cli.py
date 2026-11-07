"""The command line overlays its options on a profile; the log follows the
data folder; the helper that finishes "Remove all data" deletes only a data
folder, once the app has exited."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from gametl.app import main as main_module
from gametl.app.config import ProfileStore, Settings
from gametl.app.main import (
    build_parser,
    finish_removal_command,
    main,
    open_window_titles,
    settings_from_args,
    show_settings_if_start_fails,
    utf8_console,
)


def test_cli_options_override_profile_only_when_given() -> None:
    base = Settings(window_match="Fake Game", target_lang="de", translator="uppercase", fps=5.0, center_area=True)
    args = build_parser().parse_args(
        [
            "--target-lang",
            "tr",
            "--ignore",
            "0,0,1,0.1",
            "--no-hide-unfocused",
            "--exclude-from-capture",
            "--change-threshold",
            "0",
            "--autosave-seconds",
            "2.5",
            "--subtitle-weight",
            "bold",
            "--no-center-area",
        ]
    )
    s = settings_from_args(args, base)
    assert s.window_match == "Fake Game"  # kept from the profile
    assert s.translator == "uppercase"
    assert s.fps == 5.0
    assert s.target_lang == "tr"  # overridden
    assert s.change_threshold == 0.0 and s.autosave_seconds == 2.5
    assert s.subtitle_weight == "bold"
    assert settings_from_args(build_parser().parse_args([]), base).change_threshold == 20.0  # untouched when absent
    assert s.ignore_zones == ["0,0,1,0.1"]
    assert s.hide_when_unfocused is False
    assert s.exclude_from_capture is True
    assert s.center_area is False  # the profile's centring turned off
    old_spelling = build_parser().parse_args(["--no-center-zone"])  # the option's name before the rename
    assert settings_from_args(old_spelling, base).center_area is False
    assert settings_from_args(build_parser().parse_args([]), base).center_area is True
    assert settings_from_args(build_parser().parse_args(["--center-area"]), Settings()).center_area is True
    assert build_parser().parse_args(["--check-ui"]).check_ui is True


def test_window_titles_are_none_without_a_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    from gametl.capture import windows

    def no_desktop(*_args, **_kwargs):
        raise OSError("no desktop session")

    monkeypatch.setattr(windows, "list_windows", no_desktop)
    assert open_window_titles() == []  # plain `gametl` then carries on with the last profile


class FakeController(QObject):
    start_failed = Signal(str)
    running_changed = Signal(bool)


def test_a_start_of_its_own_that_fails_opens_the_settings(qapp) -> None:
    controller, opened = FakeController(), []
    show_settings_if_start_fails(controller, lambda: opened.append(True))
    controller.start_failed.emit("deepl: no key saved")
    assert opened == [True]  # the reason is in the window's banner, not only in the tray's tooltip
    controller.start_failed.emit("no visible window matching 'Fake Game'")
    assert opened == [True]  # that start only: later ones were asked for by the user

    controller, opened = FakeController(), []
    show_settings_if_start_fails(controller, lambda: opened.append(True))
    controller.running_changed.emit(True)
    controller.start_failed.emit("a later start, from the tray")
    assert opened == []


class StopHereError(Exception):
    """Ends main() at the point a test is about."""


def test_the_log_goes_to_the_data_folder_in_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folders: list[Path | None] = []

    def console(log_dir: Path | None = None) -> None:
        folders.append(log_dir)
        raise StopHereError

    monkeypatch.setattr(main_module, "utf8_console", console)
    with pytest.raises(StopHereError):
        main(["--data-dir", str(tmp_path / "data"), "--list-windows"])
    assert folders == [tmp_path / "data"]


def test_without_a_console_the_log_is_written_to_the_given_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered: list[object] = []
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setitem(sys.modules, "faulthandler", SimpleNamespace(enable=lambda **_kwargs: None))
    monkeypatch.setattr("gametl.app.cleanup.register_log", registered.append)
    monkeypatch.setattr(sys, "stdout", None)  # the windowed build
    monkeypatch.setattr(sys, "stderr", None)
    utf8_console(tmp_path / "data")
    log = sys.stdout
    try:
        print("hello")
    finally:
        log.close()
    assert registered == [log] and sys.stderr is log
    assert (tmp_path / "data" / "gametl.log").read_text(encoding="utf-8") == "hello\n"
    assert not (tmp_path / "appdata").exists()


def test_remove_all_data_refuses_while_the_app_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gametl.app.tray import SingleInstance

    store = ProfileStore(tmp_path / "data")
    store.save("game", Settings())
    monkeypatch.setattr(main_module, "utf8_console", lambda log_dir=None: None)
    monkeypatch.setattr("gametl.capture.windows.enable_per_monitor_dpi_awareness", lambda: None)
    monkeypatch.setattr(SingleInstance, "running", lambda self: True)
    assert main(["--remove-all-data", "--data-dir", str(store.root)]) == 1
    assert "is running: quit it from the tray first" in capsys.readouterr().out
    assert store.exists("game")  # nothing was deleted


def exited_pid() -> int:
    """The number of a process that has ended."""
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_the_finish_removal_command_runs_the_app_itself(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "executable", "C:/Subline/gametl.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert finish_removal_command(42, tmp_path) == ["C:/Subline/gametl.exe", "--finish-removal", "42", str(tmp_path)]
    monkeypatch.setattr(sys, "frozen", False)
    monkeypatch.setattr(sys, "executable", "python")
    command = finish_removal_command(42, tmp_path)
    assert command == ["python", "-m", "gametl.app.main", "--finish-removal", "42", str(tmp_path)]


def test_finish_removal_deletes_the_data_folder_once_the_app_has_exited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        main_module, "utf8_console", lambda log_dir=None: pytest.fail("no log: it would go in the folder")
    )
    store = ProfileStore(tmp_path / "data")
    (store.runtime_dir / "ctranslate2").mkdir(parents=True)  # what a loaded library kept from going
    (store.runtime_dir / "ctranslate2" / "ctranslate2.dll").write_bytes(b"x")
    assert main(["--finish-removal", str(exited_pid()), str(store.root)]) == 0
    assert not store.root.exists()


def test_finish_removal_deletes_nothing_but_a_data_folder(tmp_path: Path) -> None:
    other = tmp_path / "documents"
    other.mkdir()
    (other / "letter.txt").write_text("keep")
    pid = str(exited_pid())
    assert main(["--finish-removal", pid, str(other)]) == 2  # nothing the app keeps in it
    assert main(["--finish-removal", pid, str(tmp_path / "missing")]) == 2
    assert main(["--finish-removal", "not-a-pid", str(other)]) == 2
    assert main(["--finish-removal", pid]) == 2
    assert (other / "letter.txt").read_text() == "keep"
