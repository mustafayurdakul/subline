"""Settings dialog round trip and the CLI overlay of options on a profile."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtWidgets import QApplication

from gametl.app.config import ProfileStore, Settings
from gametl.app.credentials import DEEPL_KEY, MemorySecretStore
from gametl.app.license import make_key
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
        subtitle_background="none",
        subtitle_position="bottom",
        subtitle_hide_source=False,
        center_zone=False,
        font="Arial",
        fps=8.0,
        hide_when_unfocused=False,
        exclude_from_capture=True,
        hotkeys={"toggle": "ctrl+alt+t"},
    )
    dialog = SettingsDialog(original, store, MemorySecretStore())
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


def test_keys_go_to_the_secret_store_not_the_profile(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This machine may have real keys in its environment: hide them from the test.
    monkeypatch.delenv(DEEPL_KEY, raising=False)
    monkeypatch.setattr("gametl.app.credentials.user_environment_variable", lambda name: None)
    secrets = MemorySecretStore()
    dialog = SettingsDialog(Settings(), ProfileStore(tmp_path), secrets)
    assert dialog.key_labels[DEEPL_KEY].text() == "not set"
    dialog.key_edits[DEEPL_KEY].setText("abc:fx")
    dialog.apply()  # Apply saves a typed key as well as the explicit Save button
    assert secrets.get(DEEPL_KEY) == "abc:fx"
    assert dialog.key_edits[DEEPL_KEY].text() == ""  # the field is blanked once stored
    assert dialog.key_labels[DEEPL_KEY].text() == "set (memory)"
    assert "abc:fx" not in str(dialog.to_settings().to_dict())
    dialog.clear_key(DEEPL_KEY)
    assert secrets.get(DEEPL_KEY) is None
    assert dialog.key_labels[DEEPL_KEY].text() == "not set"
    dialog.close()


def test_license_tab_activates_and_removes_a_key(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    monkeypatch.setattr("gametl.app.license.PUBLIC_KEY_HEX", private.public_key().public_bytes_raw().hex())
    secrets = MemorySecretStore()
    dialog = SettingsDialog(Settings(), ProfileStore(tmp_path), secrets)
    assert dialog.license_label.text().startswith("trial: ")
    dialog.license_key.setText("GAMETL-nonsense.x")
    dialog.activate_license()
    assert dialog.license_label.text().startswith("key rejected")
    dialog.license_key.setText(make_key(pem, "Ada Lovelace", "ada@example.com", date.today()))
    dialog.activate_license()
    assert dialog.license_label.text() == "licensed to Ada Lovelace"
    assert dialog.license_key.text() == ""
    assert secrets.get(
        "LICENSE_KEY",
    ).startswith("GAMETL-")
    dialog.remove_license()
    assert dialog.license_label.text().startswith("trial: ")
    dialog.close()


def test_cli_options_override_profile_only_when_given() -> None:
    base = Settings(window_match="Fake Game", target_lang="de", translator="uppercase", fps=5.0)
    args = build_parser().parse_args(
        ["--target-lang", "tr", "--ignore", "0,0,1,0.1", "--no-hide-unfocused", "--exclude-from-capture"]
    )
    s = settings_from_args(args, base)
    assert s.window_match == "Fake Game"  # kept from the profile
    assert s.translator == "uppercase"
    assert s.fps == 5.0
    assert s.target_lang == "tr"  # overridden
    assert s.ignore_zones == ["0,0,1,0.1"]
    assert s.hide_when_unfocused is False
    assert s.exclude_from_capture is True
