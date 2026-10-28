"""The QML settings window loads every page without a display and without
a single QML error or warning. Runs in its own process: the offscreen
platform must be chosen before any Qt application exists, and the other
tests may already have one."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import gametl


def test_every_page_loads_clean() -> None:
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "QT_ENABLE_HIGHDPI_SCALING": "0",
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(Path(gametl.__file__).parents[1]), os.environ.get("PYTHONPATH")])
        ),
    }
    result = subprocess.run(
        [sys.executable, "-m", "gametl.app.settings_window", "--check"],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "7 pages loaded, 0 problems" in result.stdout, result.stdout
