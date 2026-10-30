"""Build the distributable folder with PyInstaller, and the installer.

  uv run --group build python scripts/build.py              # -> dist/gametl/
  uv run --group build python scripts/build.py --clean      # wipe build/ and dist/ first
  uv run --group build python scripts/build.py --installer  # plus dist/Subline-v<version>-setup.exe (Inno Setup 6)

Generates the app icon from the same drawing the tray uses, runs the spec,
moves the licence files up next to the executables, and prints the size of
the result.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISCC_DEFAULT = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")  # where the Inno Setup installer puts it


def find_iscc() -> str | None:
    """The Inno Setup compiler: $ISCC, then the default install path, then PATH."""
    candidate = os.environ.get("ISCC")
    if candidate and Path(candidate).exists():
        return candidate
    if ISCC_DEFAULT.exists():
        return str(ISCC_DEFAULT)
    return shutil.which("ISCC")


def build_installer(dist: Path, version: str, icon: Path) -> Path:
    """Compile installer/subline.iss around the built folder into dist/."""
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit("Inno Setup 6 not found: install it (https://jrsoftware.org/isinfo.php) or set ISCC")
    out_dir = dist.parent
    cmd = [
        iscc,
        f"/DAppVersion={version}",
        f"/DSourceDir={dist}",
        f"/DOutputDir={out_dir}",
        f"/DIconFile={icon}",
        str(ROOT / "installer" / "subline.iss"),
    ]
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
    setup = out_dir / f"Subline-v{version}-setup.exe"
    if not setup.exists():
        raise SystemExit(f"Inno Setup finished but {setup} is missing")
    return setup


def make_ico(path: Path) -> None:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    from PySide6.QtWidgets import QApplication

    from gametl.app.icon import make_icon

    app = QApplication.instance() or QApplication([])  # noqa: F841 (needed for QPixmap)
    icon = make_icon(False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not icon.pixmap(256, 256).save(str(path), "ICO"):
        raise SystemExit(f"could not write {path}")


def relocate_licences(dist: Path) -> None:
    """PyInstaller puts every data file under _internal; the licence, the
    notices and the licenses folder belong next to the executables."""
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "licenses"):
        source, target = dist / "_internal" / name, dist / name
        if source.exists():
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            shutil.move(str(source), str(target))


def folder_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clean", action="store_true", help="remove build/ and dist/ first")
    parser.add_argument("--installer", action="store_true", help="also build the Inno Setup installer into dist/")
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
    relocate_licences(dist)
    exes = sorted(p.name for p in dist.glob("*.exe"))
    print(f"\nbuilt {dist}: {folder_size(dist) / 1_000_000:.0f} MB, executables: {', '.join(exes)}")
    if args.installer:
        from gametl import __version__

        setup = build_installer(dist, __version__, ROOT / "build" / "gametl.ico")
        print(f"installer {setup}: {setup.stat().st_size / 1_000_000:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
