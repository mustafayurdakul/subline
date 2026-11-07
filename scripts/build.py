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
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISCC_DEFAULT = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")  # where the Inno Setup installer puts it
# The sizes Windows picks from for the taskbar, Explorer views, shortcuts at
# any display scale and the Apps list; ascending, the largest last.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


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
    """The app icon at every size in ICO_SIZES, each drawn at its own size
    so the small ones stay sharp. Qt's ICO writer stores one image only;
    Pillow puts them together."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication

    from gametl.app.icon import make_icon

    app = QApplication.instance() or QApplication([])  # noqa: F841 (needed for QPixmap)
    images = []
    for size in ICO_SIZES:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not make_icon(False, size=size).pixmap(size, size).save(buffer, "PNG"):
            raise SystemExit(f"could not draw the {size} px icon")
        images.append(Image.open(io.BytesIO(bytes(buffer.data()))))
    path.parent.mkdir(parents=True, exist_ok=True)
    largest = images[-1]
    try:
        largest.save(path, format="ICO", sizes=[image.size for image in images], append_images=images[:-1])
    except OSError as exc:
        raise SystemExit(f"could not write {path}: {exc}") from exc


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
