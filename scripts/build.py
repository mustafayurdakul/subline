"""Build the distributable folder with PyInstaller.

  uv run --group build python scripts/build.py          # -> dist/gametl/
  uv run --group build python scripts/build.py --clean  # wipe build/ and dist/ first

Generates the app icon from the same drawing the tray uses, runs the spec,
and prints the size of the result.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def make_ico(path: Path) -> None:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    from PySide6.QtWidgets import QApplication

    from gametl.app.tray import make_icon

    app = QApplication.instance() or QApplication([])  # noqa: F841 (needed for QPixmap)
    icon = make_icon(False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not icon.pixmap(256, 256).save(str(path), "ICO"):
        raise SystemExit(f"could not write {path}")


def folder_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clean", action="store_true", help="remove build/ and dist/ first")
    parser.add_argument(
        "--distpath", default="dist", help="output folder (default dist; use another when dist/gametl is in use)"
    )
    args = parser.parse_args()

    if args.clean:
        for name in ("build", args.distpath):
            shutil.rmtree(ROOT / name, ignore_errors=True)

    make_ico(ROOT / "build" / "gametl.ico")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(ROOT / args.distpath),
        str(ROOT / "gametl.spec"),
    ]
    print(" ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    dist = ROOT / args.distpath / "gametl"
    exes = sorted(p.name for p in dist.glob("*.exe"))
    print(f"\nbuilt {dist}: {folder_size(dist) / 1_000_000:.0f} MB, executables: {', '.join(exes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
