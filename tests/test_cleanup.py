"""Remove all data: the data folder and the secret-store entries go, what
cannot go is reported, and the log file is closed first."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from gametl.app.cleanup import (
    SECRET_NAMES,
    STALE_CONFIG_KEY,
    STALE_SECRET_NAMES,
    CleanupReport,
    describe_data,
    forget_trial,
    register_log,
    release_log,
    remove_all_data,
)
from gametl.app.config import ProfileStore, Settings
from gametl.app.credentials import DEEPL_KEY, MemorySecretStore
from gametl.translate.cache import TranslationCache


def populated(tmp_path: Path) -> tuple[ProfileStore, MemorySecretStore]:
    store = ProfileStore(tmp_path / "gametl")
    store.save("Fake Game", Settings(window_match="Fake Game"))
    store.last_profile = "fake-game"
    cache = TranslationCache(store.cache_dir / "fake-game.tr.claude.json")
    cache.put("Hello", "tr", "Merhaba")
    cache.save()
    (store.models_dir / "ocr").mkdir(parents=True)
    (store.models_dir / "ocr" / "det.onnx").write_bytes(b"\0" * 10)
    (store.root / "gametl.log").write_text("log\n", encoding="utf-8")
    store.save_config({**store.load_config(), STALE_CONFIG_KEY: 10800})
    secrets = MemorySecretStore()
    for name in SECRET_NAMES + STALE_SECRET_NAMES:
        secrets.set(name, f"value of {name}")
    secrets.set("UNRELATED", "kept")
    return store, secrets


def test_forget_trial_removes_what_0_2_left_and_nothing_else(tmp_path: Path) -> None:
    store, secrets = populated(tmp_path)
    forget_trial(store, secrets)
    assert all(secrets.get(name) is None for name in STALE_SECRET_NAMES)
    assert all(secrets.get(name) for name in SECRET_NAMES) and secrets.get("UNRELATED") == "kept"
    config = store.load_config()
    assert STALE_CONFIG_KEY not in config and config["last_profile"] == "fake-game"
    assert store.load("fake-game").window_match == "Fake Game"
    forget_trial(store, secrets)  # nothing left: harmless
    forget_trial(ProfileStore(tmp_path / "never-run"), MemorySecretStore())  # no folder: harmless


def test_everything_gametl_wrote_is_gone(tmp_path: Path) -> None:
    store, secrets = populated(tmp_path)
    assert store.root.exists() and secrets.get(DEEPL_KEY)
    report = remove_all_data(store, secrets)
    assert report.complete
    assert not store.root.exists()
    assert all(secrets.get(name) is None for name in SECRET_NAMES + STALE_SECRET_NAMES)
    assert secrets.get("UNRELATED") == "kept"  # only gametl's own entries
    assert str(store.root) in report.removed
    assert f"memory entry {DEEPL_KEY}" in report.removed
    assert "removed" in report.text and "could not" not in report.text
    # Running it again on a clean machine is harmless.
    assert remove_all_data(store, secrets).complete


class FailingSecrets(MemorySecretStore):
    def delete(self, name: str) -> None:
        if name == DEEPL_KEY:
            raise OSError("vault locked")
        super().delete(name)


def test_failures_are_reported_and_do_not_stop_the_rest(tmp_path: Path) -> None:
    store, _ = populated(tmp_path)
    secrets = FailingSecrets()
    for name in SECRET_NAMES:
        secrets.set(name, "v")
    report = remove_all_data(store, secrets)
    assert not report.complete
    assert report.failed == [f"memory entry {DEEPL_KEY}: vault locked"]
    assert not store.root.exists()  # the folder still went
    assert secrets.get(DEEPL_KEY) == "v" and secrets.get("LICENSE_KEY") is None
    assert f"could not remove memory entry {DEEPL_KEY}: vault locked" in report.text


def test_describe_data_names_the_folder_and_the_entries(tmp_path: Path) -> None:
    text = describe_data(ProfileStore(tmp_path), MemorySecretStore())
    assert str(tmp_path) in text
    assert f"gametl/{DEEPL_KEY}" in text and "LICENSE_KEY" not in text  # the stale names are not advertised


def test_release_log_closes_the_log_and_redirects_the_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    log = io.StringIO()
    monkeypatch.setattr(sys, "stdout", log)
    monkeypatch.setattr(sys, "stderr", log)
    register_log(log)
    release_log()
    assert log.closed
    assert sys.stdout is not log and sys.stderr is not log
    print("still fine")  # goes to the null device, raises nothing
    release_log()  # nothing registered: a no-op


def test_empty_report_text() -> None:
    assert CleanupReport().text == "nothing to remove"
