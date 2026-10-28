"""The QML settings window loads every page without a display and without
a single QML error or warning. Runs in its own process: the offscreen
platform must be chosen before any Qt application exists, and the other
tests may already have one."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QRect

import gametl
from gametl.app.settings_window import FRAME_ALLOWANCE, WINDOW_SIZE, screen_scale


def run_python(code: list[str]) -> subprocess.CompletedProcess:
    """`python <code>` with the offscreen platform and this checkout on the path."""
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "QT_ENABLE_HIGHDPI_SCALING": "0",
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(Path(gametl.__file__).parents[1]), os.environ.get("PYTHONPATH")])
        ),
    }
    return subprocess.run([sys.executable, *code], capture_output=True, text=True, env=env, timeout=300)


def test_every_page_loads_clean() -> None:
    result = run_python(["-m", "gametl.app.settings_window", "--check"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "7 pages loaded, 0 problems" in result.stdout, result.stdout


# A copy of the pages where Dialog.qml also imports Controls without a name,
# so its title `Label` silently becomes the Controls one: no QML warning.
SHADOWED = """
import shutil, sys, tempfile
from pathlib import Path
import gametl.app.settings_window as window

with tempfile.TemporaryDirectory() as folder:
    qml = Path(folder) / "qml"
    shutil.copytree(window.qml_dir(), qml)
    dialog = qml / "Dialog.qml"
    named = "import QtQuick.Controls.Basic as C\\n"
    dialog.write_text(dialog.read_text().replace(named, named + "import QtQuick.Controls.Basic\\n"))
    window.qml_dir = lambda: qml
    print("\\n".join(window.check()))
"""


def test_the_check_catches_a_controls_type_in_place_of_the_apps_own() -> None:
    result = run_python(["-c", SHADOWED])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "a QtQuick.Controls QQuickLabel where the app's own is meant" in result.stdout, result.stdout


def screen(dpi: float, width: int = 3840, height: int = 2100) -> SimpleNamespace:
    """A screen of `dpi` logical dots per inch whose work area is `width` x `height`."""
    return SimpleNamespace(logicalDotsPerInch=lambda: dpi, availableGeometry=lambda: QRect(0, 0, width, height))


def test_the_window_scales_with_the_screens_logical_dpi() -> None:
    assert screen_scale(screen(96)) == 1.0
    assert screen_scale(screen(144)) == 1.5  # 150 %, as most Windows laptops ship
    assert screen_scale(screen(192)) == 2.0
    assert screen_scale(screen(72)) == 1.0  # never smaller than designed
    assert screen_scale(None) == 1.0


def test_the_window_fits_the_screens_work_area() -> None:
    # 1920x1080 at 150 %: 1008 lines above a 72-line taskbar, too few for 680 x 1.5 plus the title bar.
    scale = screen_scale(screen(144, 1920, 1008))
    assert 1.3 < scale < 1.5
    assert WINDOW_SIZE.height() * scale + FRAME_ALLOWANCE.height() * 1.5 <= 1008
    assert screen_scale(screen(168, 1920, 996)) < 1.5  # 175 %: no larger than fits either
    assert screen_scale(screen(144, 1024, 700)) == 1.0  # a screen smaller still: as designed, never smaller
