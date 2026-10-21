"""Settings dialog round trip and the CLI overlay of options on a profile."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtWidgets import QApplication

from gametl.app.config import ProfileStore, Settings
from gametl.app.main import build_parser, settings_from_args
from gametl.app.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def test_dialog_round_trips_settings(qapp: QApplication, tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    original = Settings(
        window_match="Fake Game",
        game="Fake Game",
        roi="0,0.75,1,0.25",
        ignore_zones=["0,0,0.5,0.1"],
        ignore_patterns=[r"^\d+$"],
        lang="en",
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
        subtitle_background="none",
        subtitle_position="bottom",
        subtitle_hide_source=False,
        center_zone=False,
        font="Arial",
        fps=8.0,
        hide_when_unfocused=False,
        hotkeys={"toggle": "ctrl+alt+t"},
    )
    dialog = SettingsDialog(original, store)
    result = dialog.to_settings()
    assert result == Settings.from_dict(original.to_dict())

    dialog.profile_name.setText("My Game")
    saved: list[str] = []
    dialog.profile_saved.connect(saved.append)
    dialog.save_profile()
    assert saved == ["my-game"]
    assert store.load("my-game").translator == "uppercase"
    assert store.last_profile == "my-game"
    dialog.close()


def test_cli_options_override_profile_only_when_given() -> None:
    base = Settings(window_match="Fake Game", target_lang="de", translator="uppercase", fps=5.0)
    args = build_parser().parse_args(["--target-lang", "tr", "--ignore", "0,0,1,0.1", "--no-hide-unfocused"])
    s = settings_from_args(args, base)
    assert s.window_match == "Fake Game"  # kept from the profile
    assert s.translator == "uppercase"
    assert s.fps == 5.0
    assert s.target_lang == "tr"  # overridden
    assert s.ignore_zones == ["0,0,1,0.1"]
    assert s.hide_when_unfocused is False
    assert s.exclude_from_capture is True
