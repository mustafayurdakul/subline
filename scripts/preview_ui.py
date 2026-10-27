"""Render the settings window's pages to PNG without a display.

  uv run python scripts/preview_ui.py --out out/ui            # every page
  uv run python scripts/preview_ui.py --page appearance --out out/ui

Uses the offscreen platform (the window renders in software anyway), so
it runs on a machine or a CI runner with no GPU and no desktop. The pages show a
sample Alan Wake 2 profile through the real backend, with an in-memory
secret store and a temporary data folder. Made for looking at the design
while it is being built; also a cheap visual check later.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from gametl.app.settings_window import PAGES, WINDOW_SIZE


def sample_backend(folder: Path, background: str):
    from gametl.app.config import ProfileStore, Settings
    from gametl.app.credentials import DEEPL_KEY, MemorySecretStore
    from gametl.app.settings_backend import SettingsBackend

    settings = Settings(
        window_match="Alan Wake 2",
        game="Alan Wake 2",
        roi="0.0000,0.7500,1.0000,0.2500",
        translator="deepl",
        target_lang="tr",
        subtitle_background=background,
        ignore_patterns=[r"^[\W\d_]*$", r"^(Objective|Press)\b"],
    )
    secrets = MemorySecretStore()
    secrets.set(DEEPL_KEY, "sample")
    store = ProfileStore(folder)
    store.save("Alan Wake 2", settings)
    backend = SettingsBackend(settings, store, secrets, profile_name="alan-wake-2")
    backend.set_status(running=True)
    backend.set_status_text("translating Alan Wake 2 · deepl · en → tr")
    return backend


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--page", choices=[*PAGES, "all"], default="all")
    p.add_argument("--out", default="out/ui", help="folder for <page>.png")
    p.add_argument("--width", type=int, default=WINDOW_SIZE.width())
    p.add_argument("--height", type=int, default=WINDOW_SIZE.height())
    p.add_argument("--full", action="store_true", help="tall enough to show the whole page, no scrolling")
    p.add_argument(
        "--background", choices=["pill", "shadow", "none"], default="pill", help="subtitle background in the preview"
    )
    args = p.parse_args()

    from PySide6.QtCore import QSize
    from PySide6.QtGui import QGuiApplication

    from gametl.app.settings_window import SettingsWindow

    app = QGuiApplication([])

    def settle() -> None:
        for _ in range(20):
            app.processEvents()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        backend = sample_backend(Path(folder), args.background)
        view = SettingsWindow(backend)
        if view.problems:
            print("\n".join(view.problems))
            return 2
        view.setMinimumSize(QSize(0, 0))  # the app's window is fixed; a render may be any size
        view.setMaximumSize(QSize(16384, 16384))
        view.resize(args.width, args.height)
        view.show()
        pages = PAGES if args.page == "all" else [args.page]
        for page in pages:
            view.show_page(page)
            settle()
            if args.full:
                view.resize(args.width, max(args.height, int(view.rootObject().property("fullHeight"))))
                settle()
            image = view.grabWindow()
            suffix = f"-{args.background}" if page == "appearance" and args.background != "pill" else ""
            path = out / f"{page}{suffix}.png"
            if not image.save(str(path)):
                print(f"could not write {path}")
                return 2
            print(f"wrote {path} ({image.width()}x{image.height()})")
        if view.problems:
            print("\n".join(view.problems))
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
