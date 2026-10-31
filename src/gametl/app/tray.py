"""Tray icon: start/stop, pause, rescan, settings, profiles, quit; global
hotkeys; status in the tooltip. One tray app runs per user and data folder."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .. import APP_NAME
from .cleanup import remove_all_data
from .config import ProfileStore, Settings, slug
from .controller import OverlayController
from .hotkeys import GlobalHotkeys
from .icon import make_icon
from .settings_backend import SettingsBackend
from .settings_window import SettingsWindow

# Hotkeys that act on a running overlay. Registered only while one runs: a
# registered combination is taken from every other program, and idle these
# would do nothing in exchange.
SESSION_HOTKEYS = frozenset({"pause", "rescan"})


class SingleInstance(QObject):
    """Keeps a second tray app from starting beside the first. The first
    one holds a lock file and listens on a local socket; a later one finds
    the lock held, asks the first to open its settings window and quits.

    The lock file sits in the temporary folder, not the data folder, so
    "Remove all data" can delete that folder while the app runs."""

    def __init__(self, data_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        key = hashlib.sha256(str(Path(data_dir).resolve()).casefold().encode("utf-8")).hexdigest()[:16]
        self.name = f"gametl-{key}"  # one per data folder (and per user: each has a temporary folder)
        self._lock = QLockFile(str(Path(tempfile.gettempdir()) / f"{self.name}.lock"))
        self._lock.setStaleLockTime(0)  # a lock is stale only when its process is gone, never by age
        self._server: QLocalServer | None = None

    def claim(self, on_request: Callable[[], None]) -> bool:
        """True when this is the only instance; `on_request` then runs each
        time a later instance starts. False when another instance runs: it
        has been asked to show itself."""
        if not self._lock.tryLock(100):
            self._wake_first()
            return False
        QLocalServer.removeServer(self.name)  # left behind by a crash
        self._server = QLocalServer(self)
        self._server.newConnection.connect(lambda: self._answer(on_request))
        self._server.listen(self.name)
        return True

    def _answer(self, on_request: Callable[[], None]) -> None:
        assert self._server is not None
        while (socket := self._server.nextPendingConnection()) is not None:
            socket.disconnectFromServer()
            socket.deleteLater()
            on_request()

    def _wake_first(self) -> None:
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if socket.waitForConnected(1000):
            socket.disconnectFromServer()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        self._lock.unlock()


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
        self._start_problem = ""  # why the last start failed, shown in the window's banner until the next start
        self._capturing = False  # a hotkey field is recording a key press: no global hotkey is held

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
        self.pause_action.triggered.connect(self.controller.set_paused)
        self.rescan_action = self.menu.addAction("Rescan screen")
        self.rescan_action.triggered.connect(self.controller.rescan)
        self.menu.addSeparator()
        self.menu.addAction("Select area to translate...").triggered.connect(self.select_area)
        self.menu.addAction("Clear area (whole window)").triggered.connect(self.controller.clear_area)
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
        controller.running_changed.connect(self._on_running_changed)
        controller.starting_changed.connect(self._refresh_labels)
        controller.starting_changed.connect(self._on_starting)
        controller.start_failed.connect(self._on_start_failed)
        controller.paused_changed.connect(self._on_paused)
        controller.area_selected.connect(self._on_area_selected)

        self.apply_hotkeys(settings)
        self._refresh_labels()
        self.tray.show()

    # -- actions ---------------------------------------------------------------

    def toggle(self) -> None:
        self.controller.toggle(self.settings)

    def toggle_pause(self) -> None:
        self.controller.set_paused(not self.controller.paused)

    def select_area(self) -> None:
        self.controller.select_area(self.settings)

    def _on_area_selected(self, spec: str) -> None:
        self.settings.set_area(spec)
        if self.window is not None:
            self.window.backend.set("roi", spec)
        if self.profile_name:
            self.store.save(self.profile_name, self.settings)
            self._on_status(f"area {'set' if spec else 'cleared'} and saved to profile {self.profile_name}")

    def open_settings(self) -> None:
        if self.window is None:
            backend = SettingsBackend(self.settings, self.store, self.controller.secrets, self.profile_name)
            backend.applied.connect(self.apply)
            backend.settings_changed.connect(self._on_settings_edited)
            backend.stop_requested.connect(self.controller.stop)
            backend.profile_saved.connect(self._on_profile_saved)
            backend.profile_loaded.connect(self._on_profile_loaded)
            backend.profile_deleted.connect(self._on_profile_deleted)
            backend.select_area_requested.connect(self._select_area_from_window)
            backend.hotkeys_changed.connect(self._on_hotkeys_edited)
            backend.hotkey_capture_changed.connect(self._on_hotkey_capture)
            backend.remove_all_data_requested.connect(self.remove_all_data)
            backend.set_status_text(self._last_status)
            if self._start_problem:
                backend.report_problem(self._start_problem)
            self.window = SettingsWindow(backend)
            self._refresh_labels()
        elif not self.window.isVisible():
            self.window.backend.load(self.settings)  # closed since: show the settings in force, not stale edits
        self.window.present()

    def _select_area_from_window(self) -> None:
        assert self.window is not None
        self.settings = self.window.backend.to_settings(self.settings)
        self.controller.select_area(self.settings)

    def _on_settings_edited(self, settings: Settings) -> None:
        """An edit in the window: the settings in force from now on, and a
        running overlay takes them up."""
        self.settings = settings
        self.controller.apply(settings)

    def _on_hotkeys_edited(self, settings: Settings) -> None:
        """A hotkey field changed: the new combinations take effect at once."""
        self.settings.hotkeys = dict(settings.hotkeys)
        self.apply_hotkeys(self.settings)

    def _on_hotkey_capture(self, capturing: bool) -> None:
        """While a field records a key press, no global hotkey may swallow it."""
        self._capturing = capturing
        if capturing:
            self.hotkeys.unregister_all()
        else:
            self.apply_hotkeys(self.settings)

    def _on_profile_loaded(self, name: str, settings: Settings) -> None:
        self.settings = settings
        self.profile_name = name
        self.apply_hotkeys(settings)
        self.controller.apply(settings)
        self._on_status(f"profile {name} loaded")

    def apply(self, settings: Settings, hwnd: int | None = None) -> None:
        self.settings = settings
        self.apply_hotkeys(settings)
        self.controller.start(settings, hwnd)

    def apply_hotkeys(self, settings: Settings) -> None:
        """Register the hotkeys afresh (all released first, so two actions
        can swap combinations); the session's own only while the overlay
        runs. A combination another program holds is reported, not fatal."""
        self.hotkeys.unregister_all()
        if self._capturing:
            return  # registered again when the field is done
        bindings = {
            "toggle": self.toggle,
            "pause": self.toggle_pause,
            "rescan": self.controller.rescan,
            "select": self.select_area,
            "settings": self.open_settings,
        }
        if not self.controller.running:
            bindings = {name: action for name, action in bindings.items() if name not in SESSION_HOTKEYS}
        failed = [
            f"{name} ({combo})"
            for name, combo in settings.hotkeys.items()
            if name in bindings and not self.hotkeys.register(name, combo, bindings[name])
        ]
        if failed:
            self._on_status("hotkeys not registered: " + ", ".join(failed))

    def load_profile(self, name: str) -> None:
        """A profile picked from the tray menu."""
        try:
            settings = self.store.load(name)
        except (OSError, ValueError) as exc:
            self._on_status(f"could not load profile {name}: {exc}")
            return
        self.store.last_profile = name
        if self.window is not None:
            self.window.backend.load(settings)
            self.window.backend.set_profile_name(name)
        self._on_profile_loaded(name, settings)

    def remove_all_data(self) -> None:
        """Wipe everything gametl keeps on this computer, then quit. The
        settings window has already asked for confirmation."""
        self._shutdown()
        report = remove_all_data(self.store, self.controller.secrets)
        if not report.complete:
            QMessageBox.warning(None, APP_NAME, "Some data could not be removed:\n" + "\n".join(report.failed))
        self.tray.hide()
        self.app.quit()

    def quit(self) -> None:
        self._shutdown()
        self.tray.hide()
        self.app.quit()

    def _shutdown(self) -> None:
        """Stop the overlay (letting a start in progress run out), release
        the hotkeys and close the settings window."""
        self.controller.close()
        self.hotkeys.unregister_all()
        if self.window is not None:
            self.window.close()

    # -- signals -----------------------------------------------------------------

    def _on_activated(self, reason) -> None:
        # A click opens the settings, as Windows users expect; the menu is on the right button.
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_settings()

    def _on_status(self, text: str) -> None:
        self._last_status = text
        if self.window is not None:
            self.window.backend.set_status_text(text)
        self.status_action.setText(f"{APP_NAME}: {text}"[:80])
        self.tray.setToolTip(f"{APP_NAME}\n{text}"[:127])

    def _on_start_failed(self, message: str) -> None:
        """A start that did not begin (no matching window, a missing
        key...). Home shows guidance rather than the status line while idle,
        so the reason goes to the banner above every page."""
        self._start_problem = message
        if self.window is not None:
            self.window.backend.report_problem(message)

    def _on_starting(self, starting: bool) -> None:
        """A new start takes the last one's failure off the banner (not a
        problem an edit reported meanwhile: that stays until corrected)."""
        if not starting or not self._start_problem:
            return
        if self.window is not None and self.window.backend.problem == self._start_problem:
            self.window.backend.clearProblem()
        self._start_problem = ""

    def _on_running_changed(self, _running: bool) -> None:
        self.apply_hotkeys(self.settings)  # the session's hotkeys come and go with the overlay
        self._refresh_labels()

    def _on_paused(self, paused: bool) -> None:
        self.pause_action.setChecked(paused)
        self._refresh_labels()

    def _on_profile_saved(self, name: str) -> None:
        self.profile_name = name
        self._on_status(f"profile {name} saved")

    def _on_profile_deleted(self, name: str) -> None:
        """The profile in use was deleted in the window: the settings in
        force stay, but an area selected later must not write it back."""
        if self.profile_name and slug(self.profile_name) == name:
            self.profile_name = None

    def _refresh_labels(self, *_changed: object) -> None:
        """Menu labels, enabled state and icon from the controller's state
        (connected to its signals, whose argument is not needed)."""
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
