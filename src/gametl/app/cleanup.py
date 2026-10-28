"""Remove everything gametl keeps on this computer.

Two places hold data: the folder under %APPDATA%\\gametl (profiles,
translation caches, downloaded models, config.json, the log, batch job
files) and the Windows Credential Manager (the API keys, the licence key
and the trial start). Everything goes except the trial start: kept in the
Credential Manager, it restores itself on the next start, so removing the
data does not begin a new trial.
"""

from __future__ import annotations

import contextlib
import faulthandler
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import IO

from .config import ProfileStore
from .credentials import ANTHROPIC_KEY, DEEPL_KEY, SecretStore
from .license import LICENSE_SECRET

# The entries removed. license.TRIAL_SECRET is not among them: the trial must not restart.
SECRET_NAMES = (DEEPL_KEY, ANTHROPIC_KEY, LICENSE_SECRET)

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
    """Delete the Credential Manager entries (all but the trial start) and
    the data folder. Never raises: whatever could not be removed is listed
    in the report."""
    report = CleanupReport()
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
