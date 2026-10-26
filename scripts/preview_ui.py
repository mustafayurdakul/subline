"""Render the settings window's pages to PNG without a display.

  uv run python scripts/preview_ui.py --out out/ui            # every page
  uv run python scripts/preview_ui.py --page appearance --out out/ui

Uses the offscreen platform and Qt Quick's software renderer, so it runs
on a machine (or a CI runner) with no GPU and no desktop. Made for looking
at the design while it is being built; also a cheap visual check later.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

QML_DIR = Path(__file__).resolve().parents[1] / "src" / "gametl" / "app" / "qml"
PAGES = ["firstrun", "game", "appearance"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--page", choices=[*PAGES, "all"], default="all")
    p.add_argument("--out", default="out/ui", help="folder for <page>.png")
    p.add_argument("--width", type=int, default=1000)
    p.add_argument("--height", type=int, default=680)
    p.add_argument("--full", action="store_true", help="tall enough to show the whole page, no scrolling")
    p.add_argument(
        "--background", choices=["pill", "shadow", "none"], default="pill", help="subtitle background in the preview"
    )
    args = p.parse_args()

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickView

    app = QGuiApplication([])
    view = QQuickView()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.engine().addImportPath(str(QML_DIR.parent))  # the gametl.ui module lives in qml/
    view.setSource(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if view.status() != QQuickView.Status.Ready:
        for error in view.errors():
            print(error.toString())
        return 2
    view.resize(args.width, args.height)
    view.show()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pages = PAGES if args.page == "all" else [args.page]
    backend = view.rootObject().property("backend")
    backend.setProperty("subtitleBackgroundIndex", ["pill", "shadow", "none"].index(args.background))
    for page in pages:
        root = view.rootObject()
        root.setProperty("page", page)
        for _ in range(20):
            app.processEvents()
        if args.full:
            view.resize(args.width, max(args.height, int(root.property("fullHeight"))))
            for _ in range(20):
                app.processEvents()
        image = view.grabWindow()
        suffix = f"-{args.background}" if page == "appearance" and args.background != "pill" else ""
        path = out / f"{page}{suffix}.png"
        if not image.save(str(path)):
            print(f"could not write {path}")
            return 2
        print(f"wrote {path} ({image.width()}x{image.height()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
