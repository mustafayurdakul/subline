"""Remove all data: the data folder and the secret-store entries go, what
cannot go is reported, and the log file is closed first."""

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
from gametl.app.credentials import MemorySecretStore
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
    assert str(store.root) in report.removed
    assert f"memory entry {TRIAL_SECRET}" in report.removed
    assert "removed" in report.text and "could not" not in report.text
    # Running it again on a clean machine is harmless.
    assert remove_all_data(store, secrets).complete


def test_a_fresh_start_follows(tmp_path: Path) -> None:
    from datetime import date, timedelta

    from gametl.app.license import license_status

    store, secrets = populated(tmp_path)
    old = date.today() - timedelta(days=30)
    secrets.set(TRIAL_SECRET, old.isoformat())
    assert license_status(secrets, store).may_run is False  # trial over
    remove_all_data(store, secrets)
    assert license_status(secrets, store).trial_days_left == 14  # as if never run


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
    assert secrets.get(TRIAL_SECRET) is None and secrets.get(LICENSE_SECRET) == "v"
    assert "could not remove memory entry LICENSE_KEY: vault locked" in report.text


def test_describe_data_names_the_folder_and_the_entries(tmp_path: Path) -> None:
    text = describe_data(ProfileStore(tmp_path), MemorySecretStore())
    assert str(tmp_path) in text
    assert "gametl/LICENSE_KEY" in text and "gametl/TRIAL_START" in text


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
