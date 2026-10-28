"""The settings window: the QML pages under src/gametl/app/qml in a Qt Quick
view, with a SettingsBackend as `backend`.

  python -m gametl.app.settings_window --check   # load every page offscreen, report QML problems
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface

from .. import APP_NAME
from .config import ProfileStore, Settings
from .credentials import MemorySecretStore
from .icon import make_icon
from .preview import PROVIDER, PreviewImageProvider
from .settings_backend import SettingsBackend, qml_dir

PAGES = ["game", "translation", "appearance", "hotkeys", "licence", "advanced"]
WINDOW_SIZE = QSize(1000, 680)  # fixed; every page scrolls inside it
_app = None  # the application check() made, kept for the life of the process


class SettingsWindow(QQuickView):
    def __init__(self, backend: SettingsBackend) -> None:
        # Drawn by Qt Quick's software renderer: a settings form needs no
        # GPU, and a Direct3D swap chain opening beside a running game made
        # some displays flicker. (Set before the first Quick window exists.)
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
        super().__init__()
        self.backend = backend
        self.problems: list[str] = []  # QML errors and warnings, as they come
        self.setTitle(APP_NAME)
        self.setIcon(make_icon(False))
        self.setFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.MSWindowsFixedSizeDialogHint
        )
        self.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.setMinimumSize(WINDOW_SIZE)
        self.setMaximumSize(WINDOW_SIZE)
        self.resize(WINDOW_SIZE)
        self.engine().warnings.connect(self._on_warnings)
        self.rootContext().setContextProperty("backend", backend)
        self.preview = PreviewImageProvider(backend)
        self.engine().addImageProvider(PROVIDER, self.preview)
        self.setSource(QUrl.fromLocalFile(str(qml_dir() / "Main.qml")))
        self.problems += [error.toString() for error in self.errors()]

    def _on_warnings(self, warnings) -> None:
        self.problems += [warning.toString() for warning in warnings]

    def show_page(self, page: str) -> None:
        root = self.rootObject()
        if root is not None:
            root.setProperty("page", page)

    def present(self) -> None:
        """Show the window, in front, with focus; the tray and the hotkey call this."""
        self.show()
        self.raise_()
        self.requestActivate()


def check(pages: Sequence[str] = PAGES) -> list[str]:
    """Load the window and every page without a display; the QML problems
    found, empty when all is well. Sets up the offscreen platform itself,
    so call it before any Qt application exists."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    from PySide6.QtGui import QGuiApplication  # after the platform is chosen above

    global _app
    _app = app = QGuiApplication.instance() or QGuiApplication([])
    with tempfile.TemporaryDirectory() as folder:
        backend = SettingsBackend(Settings(window_match="Fake Game"), ProfileStore(Path(folder)), MemorySecretStore())
        window = SettingsWindow(backend)
        window.show()
        for page in pages:
            window.show_page(page)
            for _ in range(10):
                app.processEvents()
        problems = list(window.problems)
        # Tear down in order: the pages first (they bind to the backend), then
        # the backend, and never the application before the window.
        window.close()
        window.setSource(QUrl())
        for _ in range(5):
            app.processEvents()
        del window
        del backend
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="load every page offscreen and report QML problems")
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 2
    problems = check()
    for problem in problems:
        print(problem)
    print(f"{len(PAGES)} pages loaded, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
