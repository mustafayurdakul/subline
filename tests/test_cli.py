"""The command line overlays its options on a profile."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from gametl.app.config import Settings
from gametl.app.main import build_parser, open_window_titles, settings_from_args, show_settings_if_start_fails


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
    assert build_parser().parse_args(["--check-ui"]).check_ui is True
    chat = build_parser().parse_args(
        [
            "--render",
            "chat",
            "--chat-lines",
            "6",
            "--chat-seconds",
            "0",
            "--chat-corner",
            "top-right",
            "--chat-width",
            "50",
        ]
    )
    s = settings_from_args(chat, base)
    assert (s.render, s.chat_lines, s.chat_seconds, s.chat_corner, s.chat_width) == ("chat", 6, 0, "top-right", 50)


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
