"""The app icon scripts/build.py writes for the executables and the installer."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]


def load_build_script():
    spec = importlib.util.spec_from_file_location("build_script", ROOT / "scripts" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_icon_holds_every_size_up_to_256(qapp, tmp_path: Path) -> None:
    build = load_build_script()
    path = tmp_path / "gametl.ico"
    build.make_ico(path)
    with Image.open(path) as ico:
        assert ico.info["sizes"] == {(size, size) for size in build.ICO_SIZES}
        assert ico.size == (256, 256)  # Pillow opens the largest frame
        assert ico.getbbox() is not None  # drawn, not an empty frame
