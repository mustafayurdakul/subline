"""Tray icon: start/stop, pause, rescan, settings, profiles, quit; global
hotkeys; status in the tooltip."""

from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Qt
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .config import ProfileStore, Settings
from .controller import OverlayController
from .hotkeys import GlobalHotkeys
from .settings_dialog import SettingsDialog


def make_icon(running: bool, paused: bool = False) -> QIcon:
    """A rounded square with a 'T', with a status dot: drawn in code so the
    app needs no image assets."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(30, 40, 70))
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setPen(QColor(255, 255, 255))
    font = QFont("Segoe UI", 30)
    font.setBold(True)
    p.setFont(font)
    p.drawText(pixmap.rect().adjusted(0, -2, 0, -2), Qt.AlignmentFlag.AlignCenter, "T")
    if running:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(250, 200, 60) if paused else QColor(80, 220, 120))
        p.drawEllipse(42, 42, 16, 16)
    p.end()
    return QIcon(pixmap)


class TrayApp(QObject):
    def __init__(
        self,
        app: QApplication,
        controller: OverlayController,
        store: ProfileStore,
        settings: Settings,
        profile_name: str | None = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.controller = controller
        self.store = store
        self.settings = settings
        self.profile_name = profile_name
        self.dialog: SettingsDialog | None = None
        self._last_status = ""

        self.hotkeys = GlobalHotkeys()
        app.installNativeEventFilter(self.hotkeys)

        self.tray = QSystemTrayIcon(make_icon(False))
        self.menu = QMenu()
        self.status_action = QAction("gametl: idle", self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        self.menu.addSeparator()
        self.start_action = self.menu.addAction("Start overlay")
        self.start_action.triggered.connect(self.toggle)
        self.pause_action = self.menu.addAction("Pause")
        self.pause_action.setCheckable(True)
        self.pause_action.triggered.connect(lambda checked: self.controller.set_paused(bool(checked)))
        self.rescan_action = self.menu.addAction("Rescan screen")
        self.rescan_action.triggered.connect(self.controller.rescan)
        self.menu.addSeparator()
        self.menu.addAction("Settings...").triggered.connect(self.open_settings)
        self.profiles_menu = self.menu.addMenu("Profiles")
        self.profiles_menu.aboutToShow.connect(self._rebuild_profiles_menu)
        self.menu.addAction("Open data folder").triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))
        )
        self.menu.addSeparator()
        self.menu.addAction("Quit").triggered.connect(self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)

        controller.status.connect(self._on_status)
        controller.running_changed.connect(self._on_running)
        controller.paused_changed.connect(self._on_paused)

        self.apply_hotkeys(settings)
        self._refresh_labels()
        self.tray.show()

    # -- actions ---------------------------------------------------------------

    def toggle(self) -> None:
        self.controller.toggle(self.settings)

    def toggle_pause(self) -> None:
        if self.controller.running:
            self.controller.set_paused(not self.controller.paused)

    def open_settings(self) -> None:
        if self.dialog is None:
            self.dialog = SettingsDialog(self.settings, self.store)
            self.dialog.applied.connect(self.apply)
            self.dialog.profile_saved.connect(self._on_profile_saved)
        else:
            self.dialog.load_settings(self.settings)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def apply(self, settings: Settings, hwnd: int | None = None) -> None:
        self.settings = settings
        self.apply_hotkeys(settings)
        self.controller.start(settings, hwnd)

    def apply_hotkeys(self, settings: Settings) -> None:
        self.hotkeys.unregister_all()
        bindings = {
            "toggle": self.toggle,
            "pause": self.toggle_pause,
            "rescan": self.controller.rescan,
            "settings": self.open_settings,
        }
        failed = [
            f"{name} ({combo})"
            for name, combo in settings.hotkeys.items()
            if name in bindings and not self.hotkeys.register(name, combo, bindings[name])
        ]
        if failed:
            self._on_status("hotkeys not registered: " + ", ".join(failed))

    def load_profile(self, name: str) -> None:
        try:
            self.settings = self.store.load(name)
        except (OSError, ValueError) as exc:
            self._on_status(f"could not load profile {name}: {exc}")
            return
        self.profile_name = name
        self.store.last_profile = name
        self.apply_hotkeys(self.settings)
        if self.dialog is not None:
            self.dialog.load_settings(self.settings)
        self._on_status(f"profile {name} loaded")

    def quit(self) -> None:
        self.controller.stop()
        self.hotkeys.unregister_all()
        self.tray.hide()
        self.app.quit()

    # -- signals -----------------------------------------------------------------

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings()

    def _on_status(self, text: str) -> None:
        self._last_status = text
        self.status_action.setText(f"gametl: {text}"[:80])
        self.tray.setToolTip(f"gametl\n{text}"[:127])

    def _on_running(self, running: bool) -> None:
        self._refresh_labels()

    def _on_paused(self, paused: bool) -> None:
        self.pause_action.setChecked(paused)
        self._refresh_labels()

    def _on_profile_saved(self, name: str) -> None:
        self.profile_name = name
        self._on_status(f"profile {name} saved")

    def _refresh_labels(self) -> None:
        running = self.controller.running
        self.start_action.setText("Stop overlay" if running else "Start overlay")
        self.pause_action.setEnabled(running)
        self.rescan_action.setEnabled(running)
        self.tray.setIcon(make_icon(running, self.controller.paused))

    def _rebuild_profiles_menu(self) -> None:
        self.profiles_menu.clear()
        names = self.store.list()
        if not names:
            self.profiles_menu.addAction("(none saved)").setEnabled(False)
            return
        for name in names:
            action = self.profiles_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == self.profile_name)
            action.triggered.connect(lambda _checked=False, n=name: self.load_profile(n))
