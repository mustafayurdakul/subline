"""Remove everything gametl keeps on this computer.

Two places hold data: the folder under %APPDATA%\\gametl (profiles,
translation caches, downloaded models and the offline runtime,
config.json, the log, batch job files) and the Windows Credential Manager
(the API keys).
"""

from __future__ import annotations

import contextlib
import faulthandler
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from .config import ProfileStore
from .credentials import ANTHROPIC_KEY, DEEPL_KEY, SecretStore

SECRET_NAMES = (DEEPL_KEY, ANTHROPIC_KEY)  # the Credential Manager entries the app keeps

# Up to 0.3.2, Qt Quick kept the settings window's compiled pages here, named after the
# executable (the tray app, the command-line build); now it keeps none (settings_window.py).
QML_CACHE_APPS = ("gametl", "gametl-cli")

# What earlier versions kept and this one does not: up to 0.2.1 the licence key and the trial
# (two Credential Manager entries, a registry key and a key in config.json), in 0.3.0 and
# 0.3.1 the screen reader's API key.
STALE_SECRET_NAMES = ("LICENSE_KEY", "TRIAL_USED", "SCREEN_API_KEY")
STALE_REGISTRY_KEY = r"Software\Subline"
STALE_CONFIG_KEY = "trial_used"

_log: IO[str] | None = None


def register_log(log: IO[str]) -> None:
    """Remember the log file the windowed build writes to, so a cleanup can
    close it before deleting the folder it lives in (Windows refuses to
    delete an open file)."""
    global _log
    _log = log


def release_log() -> None:
    """Close the registered log file; stdout and stderr, if they were the
    log, go to the null device from here on."""
    global _log
    log, _log = _log, None
    if log is None:
        return
    with contextlib.suppress(Exception):
        faulthandler.disable()
    sink = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 (stays open for the process)
    if sys.stdout is log:
        sys.stdout = sink
    if sys.stderr is log:
        sys.stderr = sink
    with contextlib.suppress(Exception):
        log.close()


def _forget_qml_caches() -> None:
    """Delete the folders where Qt Quick kept compiled pages up to 0.3.2,
    and their parents once empty (Qt made them). Never raises."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return
    for name in QML_CACHE_APPS:
        path = Path(base) / name / "cache" / "qmlcache"
        shutil.rmtree(path, ignore_errors=True)
        for parent in (path.parent, path.parent.parent):
            with contextlib.suppress(OSError):
                parent.rmdir()  # only when empty: never someone else's files


def forget_old_versions(store: ProfileStore, secrets: SecretStore) -> None:
    """Remove what earlier versions left behind (see STALE_* and the QML
    cache). Run at every start; after the first there is nothing to do.
    Never raises."""
    _forget_qml_caches()
    for name in STALE_SECRET_NAMES:
        with contextlib.suppress(Exception):
            secrets.delete(name)
    config = store.load_config()
    if STALE_CONFIG_KEY in config:
        del config[STALE_CONFIG_KEY]
        with contextlib.suppress(OSError):
            store.save_config(config)
    try:
        import winreg

        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, STALE_REGISTRY_KEY)
    except (ImportError, AttributeError, OSError):  # not Windows, or no such key
        pass


def describe_data(store: ProfileStore, secrets: SecretStore) -> str:
    """Where the data "Remove all data" deletes lives, for the settings window."""
    entries = ", ".join(f"gametl/{name}" for name in SECRET_NAMES)
    return f"Folder: {store.root}\n{secrets.description} entries: {entries}"


@dataclass
class CleanupReport:
    removed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # "what: why"

    @property
    def complete(self) -> bool:
        return not self.failed

    @property
    def text(self) -> str:
        lines = [f"removed {item}" for item in self.removed]
        lines += [f"could not remove {item}" for item in self.failed]
        return "\n".join(lines) or "nothing to remove"


def remove_all_data(store: ProfileStore, secrets: SecretStore) -> CleanupReport:
    """Delete the Credential Manager entries and the data folder. Never raises: whatever could not be removed is listed
    in the report."""
    report = CleanupReport()
    forget_old_versions(store, secrets)
    for name in SECRET_NAMES:
        try:
            secrets.delete(name)
        except Exception as exc:  # a vault error must not stop the rest
            report.failed.append(f"{secrets.description} entry {name}: {exc}")
        else:
            report.removed.append(f"{secrets.description} entry {name}")
    release_log()
    root = store.root
    if root.exists():

        def record(_function, path, exc) -> None:
            report.failed.append(f"{path}: {exc}")

        shutil.rmtree(root, onexc=record)
        if not root.exists():
            report.removed.append(str(root))
    return report
