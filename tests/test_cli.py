"""The command line overlays its options on a profile."""

from __future__ import annotations

from gametl.app.config import Settings
from gametl.app.main import build_parser, settings_from_args


def test_cli_options_override_profile_only_when_given() -> None:
    base = Settings(window_match="Fake Game", target_lang="de", translator="uppercase", fps=5.0)
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
    assert build_parser().parse_args(["--check-ui"]).check_ui is True
