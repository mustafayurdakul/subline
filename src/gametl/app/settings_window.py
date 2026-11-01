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

import shiboken6
from PySide6.QtCore import QEvent, QMetaObject, QObject, QSize, Qt, QUrl
from PySide6.QtGui import QScreen
from PySide6.QtQuick import QQuickItem, QQuickView, QQuickWindow, QSGRendererInterface

from .. import APP_NAME
from .config import ProfileStore, Settings
from .credentials import MemorySecretStore
from .icon import make_icon
from .preview import PROVIDER, PreviewImageProvider
from .settings_backend import SettingsBackend, qml_dir

PAGES = ["home", "game", "translation", "appearance", "hotkeys", "advanced"]  # as Main.qml's table
WINDOW_SIZE = QSize(1000, 680)  # at 96 dpi, scaled to the screen; fixed, every page scrolls inside it
# What the system adds around the window's client area at 96 dpi: the title bar and the borders.
FRAME_ALLOWANCE = QSize(16, 40)
# The app's Label and Dialog share their names with QtQuick.Controls types. A
# file that imports Controls without a qualifier silently gets the Controls
# ones instead (a dialog pinned to a corner, labels in the wrong font), so
# the check looks for them.
FOREIGN_TYPES = ("QQuickLabel", "QQuickDialog")
_app = None  # the application check() made, kept for the life of the process


def screen_scale(screen: QScreen | None) -> float:
    """The window's scale on `screen`: its logical DPI over 96, but no more
    than lets the window, title bar included, fit the screen's work area,
    and never below 1. The process runs with Qt's high-DPI scaling off, as
    the overlay needs physical pixels, so nothing else enlarges the window
    on a 150 % screen.

    The fit matters because the window has a fixed size: a 1920x1080 screen
    at 150 % has about 1000 lines above the taskbar, and 680 lines at 1.5
    plus the title bar do not fit, which would leave the bottom of every
    page out of reach. The pages scroll, so a slightly smaller scale costs
    nothing."""
    if screen is None:
        return 1.0
    scale = screen.logicalDotsPerInch() / 96
    area = screen.availableGeometry()
    if not area.isEmpty():
        frame = FRAME_ALLOWANCE * scale  # the title bar grows with the screen's scale too
        fit = min(
            (area.width() - frame.width()) / WINDOW_SIZE.width(),
            (area.height() - frame.height()) / WINDOW_SIZE.height(),
        )
        scale = min(scale, fit)
    return max(1.0, scale)


class SettingsWindow(QQuickView):
    def __init__(self, backend: SettingsBackend, scale: float | None = None) -> None:
        """`scale` fixes the window's scale (renders, tests); by default it
        follows the screen the window is on."""
        # Drawn by Qt Quick's software renderer: a settings form needs no
        # GPU, and a Direct3D swap chain opening beside a running game made
        # some displays flicker. (Set before the first Quick window exists.)
        if QQuickWindow.sceneGraphBackend() != "software":  # a second window finds it set
            QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
        super().__init__()
        self.backend = backend
        self.problems: list[str] = []  # QML errors and warnings, as they come
        self._fixed_scale = scale
        self.ui_scale = scale or screen_scale(self.screen())
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
        self._fit_to_scale()
        self.engine().warnings.connect(self._on_warnings)
        # The pages are laid out at 96 dpi; Main.qml draws them `uiScale` times as large.
        self.rootContext().setContextProperty("uiScale", self.ui_scale)
        self.rootContext().setContextProperty("backend", backend)
        self.preview = PreviewImageProvider(backend)
        self.engine().addImageProvider(PROVIDER, self.preview)
        self.setSource(QUrl.fromLocalFile(str(qml_dir() / "Main.qml")))
        self.problems += [error.toString() for error in self.errors()]
        self.screenChanged.connect(self._on_screen_changed)

    def _fit_to_scale(self) -> None:
        size = WINDOW_SIZE * self.ui_scale
        self.setMinimumSize(size)
        self.setMaximumSize(size)
        self.resize(size)

    def _on_screen_changed(self, screen: QScreen | None) -> None:
        """Moved to a screen with another scale or size: the window and its pages follow."""
        scale = screen_scale(screen)
        if self._fixed_scale is None and scale != self.ui_scale:
            self.ui_scale = scale
            self.rootContext().setContextProperty("uiScale", scale)
            self._fit_to_scale()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Close:
            # A field that writes only when it is left (`live: false`) is left
            # now, so what was typed in it is kept, not lost with the window.
            focused = self.activeFocusItem()
            if focused is not None:
                focused.setFocus(False)
        return super().event(event)

    def _on_warnings(self, warnings) -> None:
        self.problems += [warning.toString() for warning in warnings]

    def show_page(self, page: str) -> None:
        root = self.rootObject()
        if root is not None:
            root.setProperty("page", page)

    def page_keys(self) -> list[str]:
        """The page keys in Main.qml's table, in navigation order."""
        root = self.rootObject()
        pages = root.property("pages") if root is not None else None
        if hasattr(pages, "toVariant"):  # a JavaScript array arrives as a QJSValue
            pages = pages.toVariant()
        return [page["key"] for page in pages or []]

    def objects(self) -> list[QObject]:
        """Everything in the window: the item tree, where Repeater and Loader
        items hang, and each object's own children (popups, handlers)."""
        found: dict[int, QObject] = {}
        stack: list[QObject] = [self.contentItem()]
        while stack:
            obj = stack.pop()
            address = shiboken6.getCppPointer(obj)[0]
            if address in found:
                continue
            found[address] = obj
            stack += obj.children()
            if isinstance(obj, QQuickItem):
                stack += obj.childItems()
        return list(found.values())

    def popups(self) -> list[QObject]:
        """Every popup the current page and the window hold (dialogs, drop-down lists)."""
        return [obj for obj in self.objects() if _inherits(obj, "QQuickPopup")]

    def foreign_types(self) -> list[str]:
        """Class names of Controls types that stand where the app's own were meant (FOREIGN_TYPES)."""
        return sorted({name for obj in self.objects() for name in FOREIGN_TYPES if _inherits(obj, name)})

    def present(self) -> None:
        """Show the window, in front, with focus; the tray and the hotkey call this."""
        self.show()
        self.raise_()
        self.requestActivate()


def _inherits(obj: QObject, class_name: str) -> bool:
    meta = obj.metaObject()
    while meta is not None:
        if meta.className() == class_name:
            return True
        meta = meta.superClass()
    return False


def check(pages: Sequence[str] = PAGES) -> list[str]:
    """Load the window and every page without a display, opening each
    popup once; the QML problems found, empty when all is well. Sets up the
    offscreen platform itself, so call it before any Qt application exists."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    from PySide6.QtGui import QGuiApplication  # after the platform is chosen above

    global _app
    _app = app = QGuiApplication.instance() or QGuiApplication([])

    def settle(rounds: int = 10) -> None:
        for _ in range(rounds):
            app.processEvents()

    with tempfile.TemporaryDirectory() as folder:
        backend = SettingsBackend(Settings(window_match="Fake Game"), ProfileStore(Path(folder)), MemorySecretStore())
        window = SettingsWindow(backend)
        window.show()
        extra: list[str] = []
        if window.page_keys() != PAGES:
            extra.append(f"Main.qml's pages {window.page_keys()} differ from settings_window.PAGES {PAGES}")
        for page in pages:
            window.show_page(page)
            settle()
            for popup in window.popups():
                QMetaObject.invokeMethod(popup, "open")
                settle()
                QMetaObject.invokeMethod(popup, "close")
                settle()
            extra += [
                f"{page}: a QtQuick.Controls {name} where the app's own is meant" for name in window.foreign_types()
            ]
        problems = list(window.problems) + extra
        # Tear down in order: the pages first (they bind to the backend), then
        # the backend, and never the application before the window.
        window.close()
        window.setSource(QUrl())
        settle(5)
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
