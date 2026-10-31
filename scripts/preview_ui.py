"""Render the settings window's pages to PNG without a display.

  uv run python scripts/preview_ui.py --out out/ui            # every page
  uv run python scripts/preview_ui.py --page appearance --out out/ui
  uv run python scripts/preview_ui.py --scale 1.5 --profiles --out out/ui-150

Uses the offscreen platform (the window renders in software anyway), so
it runs on a machine or a CI runner with no GPU and no desktop. The pages show a
sample Alan Wake 2 profile through the real backend, with an in-memory
secret store and a temporary data folder. Made for looking at the design
while it is being built; also a cheap visual check later. `--scale` draws
the window as on a screen of that many times 96 dpi (1.5 for 150 %).
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


def sample_backend(folder: Path, background: str, translator: str = "deepl", render: str = "subtitle"):
    from gametl.app.config import ProfileStore, Settings
    from gametl.app.credentials import DEEPL_KEY, MemorySecretStore
    from gametl.app.settings_backend import SettingsBackend

    settings = Settings(
        window_match="Alan Wake 2",
        game="Alan Wake 2",
        roi="0.0000,0.7500,1.0000,0.2500",
        translator=translator,
        target_lang="tr",
        subtitle_background=background,
        render=render,
        ignore_patterns=[r"^[\W\d_]*$", r"^(Objective|Press)\b"],
    )
    secrets = MemorySecretStore()
    secrets.set(DEEPL_KEY, "sample")
    store = ProfileStore(folder)
    store.save("Alan Wake 2", settings)
    store.save("Control", Settings(window_match="Control", game="Control"))
    backend = SettingsBackend(settings, store, secrets, profile_name="alan-wake-2")
    backend.set_status(running=True)
    backend.set_status_text(f"translating Alan Wake 2 · {translator} · en → tr")
    return backend


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--page", choices=[*PAGES, "all"], default="all")
    p.add_argument("--out", default="out/ui", help="folder for <page>.png")
    p.add_argument("--scale", type=float, default=1.0, help="screen scale: 1.5 draws as on a 150 %% screen")
    p.add_argument("--width", type=int, help="window width in pixels (default: the app's, at the scale)")
    p.add_argument("--height", type=int, help="window height in pixels (default: the app's, at the scale)")
    p.add_argument("--full", action="store_true", help="tall enough to show the whole page, no scrolling")
    p.add_argument(
        "--background", choices=["pill", "shadow", "none"], default="pill", help="subtitle background in the preview"
    )
    p.add_argument(
        "--translator", choices=["deepl", "claude", "offline"], default="deepl", help="the sample's translator"
    )
    p.add_argument("--render", choices=["subtitle", "chat", "inplace"], default="subtitle", help="the sample's mode")
    p.add_argument("--profiles", action="store_true", help="also render the Profiles popup, open over Home")
    args = p.parse_args()
    width = args.width or round(WINDOW_SIZE.width() * args.scale)
    height = args.height or round(WINDOW_SIZE.height() * args.scale)

    from PySide6.QtCore import QMetaObject, QSize
    from PySide6.QtGui import QGuiApplication

    from gametl.app.settings_window import SettingsWindow

    app = QGuiApplication([])

    def settle() -> None:
        for _ in range(20):
            app.processEvents()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def save(view, name: str) -> bool:
        image = view.grabWindow()
        path = out / f"{name}.png"
        if not image.save(str(path)):
            print(f"could not write {path}")
            return False
        print(f"wrote {path} ({image.width()}x{image.height()})")
        return True

    with tempfile.TemporaryDirectory() as folder:
        backend = sample_backend(Path(folder), args.background, args.translator, args.render)
        view = SettingsWindow(backend, scale=args.scale)
        if view.problems:
            print("\n".join(view.problems))
            return 2
        view.setMinimumSize(QSize(0, 0))  # the app's window is fixed; a render may be any size
        view.setMaximumSize(QSize(16384, 16384))
        view.resize(width, height)
        view.show()
        pages = PAGES if args.page == "all" else [args.page]
        for page in pages:
            view.show_page(page)
            settle()
            if args.full:
                view.resize(width, max(height, int(view.rootObject().property("fullHeight"))))
                settle()
            suffix = ""
            if page == "appearance":
                suffix = "".join(f"-{v}" for v in (args.background, args.render) if v not in ("pill", "subtitle"))
            if not save(view, page + suffix):
                return 2
        if args.profiles:
            view.resize(width, height)
            view.show_page("home")
            settle()
            (popup,) = [obj for obj in view.popups() if obj.metaObject().className().startswith("ProfilePopup")]
            QMetaObject.invokeMethod(popup, "open")
            settle()
            if not save(view, "profiles"):
                return 2
        if view.problems:
            print("\n".join(view.problems))
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
