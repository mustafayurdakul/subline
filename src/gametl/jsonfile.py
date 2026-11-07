"""Crash-safe writes for the app's own files (config, profiles, translation
caches, batch jobs)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    """Write `text` to a temporary file beside `path`, flush it to the disk,
    then put it in place: a crash, a power cut or a full disk mid-write
    leaves the old file intact, never a truncated or zero-filled one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            # The rename can reach the disk before the data does: without this,
            # a power cut just after a save can leave the new name holding nothing.
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)  # only left over when the write failed


def write_json_atomic(path: Path, data: object, indent: int = 2) -> None:
    """`data` as JSON (UTF-8, non-ASCII kept as it is), written as `write_text_atomic` does."""
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=indent))
