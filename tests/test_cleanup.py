"""Remove all data: the data folder and the secret-store entries go, what
cannot go is reported, and the log file is closed first."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from gametl.app.cleanup import (
    SECRET_NAMES,
    STALE_CONFIG_KEY,
    STALE_REGISTRY_KEY,
    STALE_SECRET_NAMES,
    CleanupReport,
    describe_data,
    forget_old_versions,
    register_log,
    release_log,
    remove_all_data,
)
from gametl.app.config import ProfileStore, Settings
from gametl.app.credentials import ANTHROPIC_KEY, DEEPL_KEY, MemorySecretStore
from gametl.translate.cache import TranslationCache


@pytest.fixture(autouse=True)
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """The cleanup acts on a stand-in machine: LOCALAPPDATA in the test's
    folder and a registry that records the keys deleted (returned)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    deleted: list[tuple[str, str]] = []
    registry = SimpleNamespace(HKEY_CURRENT_USER="HKCU", DeleteKey=lambda root, key: deleted.append((root, key)))
    monkeypatch.setitem(sys.modules, "winreg", registry)
    return deleted


@pytest.fixture
def no_faulthandler(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """release_log() turns the fault handler off; pytest's own must stay on
    for the rest of the run. Returns a list that records each call."""
    disabled: list[bool] = []
    monkeypatch.setattr("gametl.app.cleanup.faulthandler", SimpleNamespace(disable=lambda: disabled.append(True)))
    return disabled


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


def test_forget_old_versions_removes_stale_entries_and_nothing_else(tmp_path: Path, machine) -> None:
    store, secrets = populated(tmp_path)
    forget_old_versions(store, secrets)
    assert ("HKCU", STALE_REGISTRY_KEY) in machine
    assert all(secrets.get(name) is None for name in STALE_SECRET_NAMES)
    assert all(secrets.get(name) for name in SECRET_NAMES) and secrets.get("UNRELATED") == "kept"
    config = store.load_config()
    assert STALE_CONFIG_KEY not in config and config["last_profile"] == "fake-game"
    assert store.load("fake-game").window_match == "Fake Game"
    forget_old_versions(store, secrets)  # nothing left: harmless
    forget_old_versions(ProfileStore(tmp_path / "never-run"), MemorySecretStore())  # no folder: harmless


def test_the_old_qml_cache_goes_and_nothing_else(tmp_path: Path) -> None:
    for name in ("gametl", "gametl-cli"):
        cache = tmp_path / "local" / name / "cache" / "qmlcache"
        cache.mkdir(parents=True)
        (cache / "page.qmlc").write_bytes(b"x")
    (tmp_path / "local" / "gametl-cli" / "keep.txt").write_text("not Qt's")
    store, secrets = populated(tmp_path)
    forget_old_versions(store, secrets)
    assert not (tmp_path / "local" / "gametl").exists()  # the cache and the folders Qt made for it
    assert not (tmp_path / "local" / "gametl-cli" / "cache").exists()
    assert (tmp_path / "local" / "gametl-cli" / "keep.txt").exists()  # a folder with other files stays
    forget_old_versions(store, secrets)  # nothing left: harmless


def test_the_settings_window_keeps_no_qml_cache() -> None:
    import gametl.app.settings_window  # noqa: F401 (sets the environment on import)

    assert os.environ["QML_DISABLE_DISK_CACHE"] == "1"


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
    assert secrets.get(DEEPL_KEY) == "v" and secrets.get(ANTHROPIC_KEY) is None  # the next entry still went
    assert f"could not remove memory entry {DEEPL_KEY}: vault locked" in report.text


def test_describe_data_names_the_folder_and_the_entries(tmp_path: Path) -> None:
    text = describe_data(ProfileStore(tmp_path), MemorySecretStore())
    assert str(tmp_path) in text
    assert f"gametl/{DEEPL_KEY}" in text and not any(name in text for name in STALE_SECRET_NAMES)  # not advertised


def test_release_log_closes_the_log_and_redirects_the_streams(monkeypatch: pytest.MonkeyPatch, no_faulthandler) -> None:
    log = io.StringIO()
    monkeypatch.setattr(sys, "stdout", log)
    monkeypatch.setattr(sys, "stderr", log)
    register_log(log)
    release_log()
    sink = sys.stdout
    try:
        assert log.closed and no_faulthandler == [True]
        assert sys.stdout is not log and sys.stderr is not log
        print("still fine")  # goes to the null device, raises nothing
        release_log()  # nothing registered: a no-op
    finally:
        sink.close()


def test_remove_all_data_closes_the_open_log_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_faulthandler
) -> None:
    # The windowed build's state: the log in the data folder, open, as stdout (Windows cannot delete an open file).
    store, secrets = populated(tmp_path)
    log = open(store.root / "gametl.log", "a", encoding="utf-8")  # noqa: SIM115 (closed by remove_all_data)
    monkeypatch.setattr(sys, "stdout", log)
    register_log(log)
    report = remove_all_data(store, secrets)
    sys.stdout.close()  # the null device it was redirected to
    assert log.closed and report.complete and not store.root.exists()


def test_empty_report_text() -> None:
    assert CleanupReport().text == "nothing to remove"
