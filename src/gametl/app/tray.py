"""Tray icon: start/stop, pause, rescan, settings, profiles, quit; global
hotkeys; status in the tooltip."""

from __future__ import annotations

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .. import APP_NAME
from .cleanup import remove_all_data
from .config import ProfileStore, Settings
from .controller import OverlayController
from .hotkeys import GlobalHotkeys
from .icon import make_icon
from .license import license_status
from .settings_backend import SettingsBackend
from .settings_window import SettingsWindow


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
        self.window: SettingsWindow | None = None
        self._last_status = ""

        self.hotkeys = GlobalHotkeys()
        app.installNativeEventFilter(self.hotkeys)

        self.tray = QSystemTrayIcon(make_icon(False))
        self.menu = QMenu()
        self.status_action = QAction(f"{APP_NAME}: idle", self.menu)
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
        self.menu.addAction("Select area to translate...").triggered.connect(self.select_area)
        self.clear_area_action = self.menu.addAction("Clear area (whole window)")
        self.clear_area_action.triggered.connect(self.clear_area)
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
        controller.starting_changed.connect(self._on_starting)
        controller.paused_changed.connect(self._on_paused)
        controller.area_selected.connect(self._on_area_selected)

        self.apply_hotkeys(settings)
        self._refresh_labels()
        self._on_status(license_status(controller.secrets, store).text)
        self.tray.show()

    # -- actions ---------------------------------------------------------------

    def toggle(self) -> None:
        self.controller.toggle(self.settings)

    def toggle_pause(self) -> None:
        if self.controller.running:
            self.controller.set_paused(not self.controller.paused)

    def select_area(self) -> None:
        self.controller.select_area(self.settings)

    def clear_area(self) -> None:
        self.controller.clear_area()

    def _on_area_selected(self, spec: str) -> None:
        self.settings.roi = spec
        if spec:
            self.settings.full_scan_every = 0
        if self.window is not None:
            self.window.backend.set("roi", spec)
        if self.profile_name:
            self.store.save(self.profile_name, self.settings)
            self._on_status(f"area {'set' if spec else 'cleared'} and saved to profile {self.profile_name}")

    def open_settings(self) -> None:
        if self.window is None:
            backend = SettingsBackend(self.settings, self.store, self.controller.secrets, self.profile_name)
            backend.applied.connect(self.apply)
            backend.stop_requested.connect(self.controller.stop)
            backend.profile_saved.connect(self._on_profile_saved)
            backend.profile_loaded.connect(self._on_profile_loaded)
            backend.select_area_requested.connect(self._select_area_from_window)
            backend.hotkeys_changed.connect(self._on_hotkeys_edited)
            backend.hotkey_capture_changed.connect(self._on_hotkey_capture)
            backend.remove_all_data_requested.connect(self.remove_all_data)
            backend.set_status_text(self._last_status)
            self.window = SettingsWindow(backend)
            self._refresh_labels()
        elif not self.window.isVisible():
            self.window.backend.load(self.settings)  # closed since: show the settings in force, not stale edits
        self.window.present()

    def _select_area_from_window(self) -> None:
        assert self.window is not None
        self.settings = self.window.backend.to_settings(self.settings)
        self.controller.select_area(self.settings)

    def _on_hotkeys_edited(self, settings: Settings) -> None:
        """A hotkey field changed: the new combinations take effect at once."""
        self.settings.hotkeys = dict(settings.hotkeys)
        self.apply_hotkeys(self.settings)

    def _on_hotkey_capture(self, capturing: bool) -> None:
        """While a field records a key press, no global hotkey may swallow it."""
        if capturing:
            self.hotkeys.unregister_all()
        else:
            self.apply_hotkeys(self.settings)

    def _on_profile_loaded(self, name: str, settings: Settings) -> None:
        self.settings = settings
        self.profile_name = name
        self.apply_hotkeys(settings)
        self._on_status(f"profile {name} loaded")

    def apply(self, settings: Settings, hwnd: int | None = None) -> None:
        self.settings = settings
        self.apply_hotkeys(settings)
        self.controller.start(settings, hwnd)

    def apply_hotkeys(self, settings: Settings) -> None:
        """Register every hotkey afresh; a combination another program holds is reported, not fatal."""
        self.hotkeys.unregister_all()
        bindings = {
            "toggle": self.toggle,
            "pause": self.toggle_pause,
            "rescan": self.controller.rescan,
            "select": self.select_area,
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
        if self.window is not None:
            self.window.backend.load(self.settings)
            self.window.backend.set_profile_name(name)
        self._on_status(f"profile {name} loaded")

    def remove_all_data(self) -> None:
        """Wipe everything gametl keeps on this computer, then quit. The
        settings window has already asked for confirmation."""
        self.controller.close()
        self.hotkeys.unregister_all()
        if self.window is not None:
            self.window.close()
        report = remove_all_data(self.store, self.controller.secrets)
        if not report.complete:
            QMessageBox.warning(None, APP_NAME, "Some data could not be removed:\n" + "\n".join(report.failed))
        self.tray.hide()
        self.app.quit()

    # -- signals -----------------------------------------------------------------

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings()

    def _on_status(self, text: str) -> None:
        self._last_status = text
        if self.window is not None:
            self.window.backend.set_status_text(text)
        self.status_action.setText(f"{APP_NAME}: {text}"[:80])
        self.tray.setToolTip(f"{APP_NAME}\n{text}"[:127])

    def _on_running(self, running: bool) -> None:
        self._refresh_labels()

    def _on_starting(self, starting: bool) -> None:
        self._refresh_labels()

    def _on_paused(self, paused: bool) -> None:
        self.pause_action.setChecked(paused)
        self._refresh_labels()

    def _on_profile_saved(self, name: str) -> None:
        self.profile_name = name
        self._on_status(f"profile {name} saved")

    def quit(self) -> None:
        self.controller.close()
        self.hotkeys.unregister_all()
        if self.window is not None:
            self.window.close()
        self.tray.hide()
        self.app.quit()

    def _refresh_labels(self) -> None:
        running, starting = self.controller.running, self.controller.starting
        # While the models load on their thread, the same action abandons the start.
        label = "Cancel start" if starting else ("Stop overlay" if running else "Start overlay")
        self.start_action.setText(label)
        self.pause_action.setEnabled(running)
        self.rescan_action.setEnabled(running)
        self.tray.setIcon(make_icon(running, self.controller.paused, starting))
        if self.window is not None:
            self.window.backend.set_status(running, starting, self.controller.paused)

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
