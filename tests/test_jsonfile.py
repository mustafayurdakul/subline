from __future__ import annotations

import json
from pathlib import Path

import pytest

import gametl.jsonfile as jsonfile
from gametl.jsonfile import write_json_atomic, write_text_atomic


def test_json_is_written_as_utf8_with_the_letters_kept(tmp_path: Path) -> None:
    path = tmp_path / "profiles" / "fake-game.json"  # the folder is made as needed
    data = {"game": "Çay Ocağı", "roi": [0.1, 0.8], "nested": {"a": 1}}
    write_json_atomic(path, data)
    assert path.read_text(encoding="utf-8") == json.dumps(data, ensure_ascii=False, indent=2)
    write_json_atomic(path, data, indent=1)
    assert path.read_text(encoding="utf-8") == json.dumps(data, ensure_ascii=False, indent=1)
    assert [p.name for p in path.parent.iterdir()] == ["fake-game.json"]


def test_a_failed_write_keeps_the_old_file_and_leaves_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    write_text_atomic(path, "old")

    def disk_full(*_args) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(jsonfile.os, "replace", disk_full)
    with pytest.raises(OSError):
        write_text_atomic(path, "new")
    assert path.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]
