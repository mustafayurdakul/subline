"""Remove all data: the data folder and the secret-store entries go (the
trial's start date stays), what cannot go is reported, and the log file is
closed first."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from gametl.app.cleanup import (
    SECRET_NAMES,
    CleanupReport,
    describe_data,
    register_log,
    release_log,
    remove_all_data,
)
from gametl.app.config import ProfileStore, Settings
from gametl.app.credentials import DEEPL_KEY, MemorySecretStore
from gametl.app.license import LICENSE_SECRET, TRIAL_SECRET
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
    secrets = MemorySecretStore()
    for name in SECRET_NAMES:
        secrets.set(name, f"value of {name}")
    secrets.set(TRIAL_SECRET, "120")  # two minutes of the trial used
    secrets.set("UNRELATED", "kept")
    return store, secrets


def test_everything_gametl_wrote_is_gone(tmp_path: Path) -> None:
    store, secrets = populated(tmp_path)
    assert store.root.exists() and secrets.get(LICENSE_SECRET)
    report = remove_all_data(store, secrets)
    assert report.complete
    assert not store.root.exists()
    assert all(secrets.get(name) is None for name in SECRET_NAMES)
    assert secrets.get("UNRELATED") == "kept"  # only gametl's own entries
    assert secrets.get(TRIAL_SECRET) == "120"  # the trial's used time stays
    assert str(store.root) in report.removed
    assert f"memory entry {LICENSE_SECRET}" in report.removed
    assert f"memory entry {TRIAL_SECRET}" not in report.removed
    assert "removed" in report.text and "could not" not in report.text
    # Running it again on a clean machine is harmless.
    assert remove_all_data(store, secrets).complete


def test_the_trial_does_not_start_again(tmp_path: Path) -> None:
    from gametl.app.license import TRIAL_SECONDS, license_status

    store, secrets = populated(tmp_path)
    secrets.set(TRIAL_SECRET, str(TRIAL_SECONDS))
    assert license_status(secrets, store).may_run is False  # trial over
    remove_all_data(store, secrets)
    assert license_status(secrets, store).may_run is False  # still over
    assert store.load_config()["trial_used"] == TRIAL_SECONDS  # and written back to a fresh config.json


class FailingSecrets(MemorySecretStore):
    def delete(self, name: str) -> None:
        if name == LICENSE_SECRET:
            raise OSError("vault locked")
        super().delete(name)


def test_failures_are_reported_and_do_not_stop_the_rest(tmp_path: Path) -> None:
    store, _ = populated(tmp_path)
    secrets = FailingSecrets()
    for name in SECRET_NAMES:
        secrets.set(name, "v")
    report = remove_all_data(store, secrets)
    assert not report.complete
    assert report.failed == [f"memory entry {LICENSE_SECRET}: vault locked"]
    assert not store.root.exists()  # the folder still went
    assert secrets.get(DEEPL_KEY) is None and secrets.get(LICENSE_SECRET) == "v"
    assert "could not remove memory entry LICENSE_KEY: vault locked" in report.text


def test_describe_data_names_the_folder_and_the_entries(tmp_path: Path) -> None:
    text = describe_data(ProfileStore(tmp_path), MemorySecretStore())
    assert str(tmp_path) in text
    assert "gametl/LICENSE_KEY" in text and "gametl/TRIAL_USED" not in text


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
