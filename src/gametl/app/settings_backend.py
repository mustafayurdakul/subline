"""The settings window's Python side: what the QML pages read and write.

`SettingsBackend.settings` is a QQmlPropertyMap with one entry per Settings
field the window shows: a page binds a control to `backend.settings.roi`
and writes back the same way. Lists hold one entry per line and the
hotkeys are flattened to `hotkey_<name>`. `to_settings()` reads the map
onto the settings last loaded, so fields without a control (stable_frames,
debug, ...) keep their values. Every edit goes out as `settings_changed`
once the typing pauses, so a running overlay follows the window. What the
window cannot do alone (run the overlay, select an area, wipe the data)
goes out as a signal to the tray, which owns the controller.
"""

from __future__ import annotations

import dataclasses
import re
import typing
import warnings
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlPropertyMap

from .. import APP_NAME, __version__
from .cleanup import describe_data
from .config import BOTTOM_STRIP, DEFAULT_HOTKEYS, ProfileStore, Settings, slug
from .credentials import ANTHROPIC_KEY, DEEPL_KEY, SecretStore, WindowsCredentialStore, key_status
from .hotkeys import parse_combo
from .license import PURCHASE_URL, TRIAL_DAYS, LicenseError, activate, deactivate, license_status

# fmt: off
OCR_LANGS = [
    "en", "ch", "chinese_cht", "japan", "korean", "de", "fr", "es", "it", "pt", "pl", "nl", "tr", "cyrillic", "arabic",
]
# fmt: on
CLAUDE_MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
HOTKEY_LABELS = {
    "toggle": "Start / stop overlay",
    "pause": "Pause / resume",
    "rescan": "Rescan screen",
    "select": "Select area to translate",
    "settings": "Open settings",
}
LIST_FIELDS = ("ignore_zones", "ignore_patterns")  # one entry per line in the window
# An emptied text control means the default, not an empty value.
EMPTY_DEFAULTS = {
    "lang": "en",
    "target_lang": "tr",
    "translator": "deepl",
    "model": CLAUDE_MODELS[0],
    "font": "Segoe UI",
}
EDIT_DELAY_MS = 500  # an edit reaches the running overlay this long after the last keystroke

_FIELD_TYPES = typing.get_type_hints(Settings)
_FIELDS = [f.name for f in dataclasses.fields(Settings) if f.name != "hotkeys"]


def _lines(text: Any) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def invalid_pattern(patterns: list[str]) -> str | None:
    """One line naming the first ignore pattern that is not a valid regular
    expression, or None when all compile."""
    for pattern in patterns:
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"Ignore pattern {pattern!r} is not a valid regular expression: {exc}"
    return None


def invalid_hotkey(hotkeys: dict[str, str]) -> str | None:
    """One line naming the first hotkey that does not parse, or None."""
    for name, combo in hotkeys.items():
        try:
            parse_combo(combo)
        except ValueError as exc:
            return f"Hotkey for {HOTKEY_LABELS.get(name, name)!r}: {exc}"
    return None


def _coerce(name: str, raw: Any, fallback: Any) -> Any:
    """A map value (which QML may have written as a string or a double) as
    the type the Settings field has; `fallback` when it does not parse."""
    kind = _FIELD_TYPES[name]
    if kind is bool:
        return bool(raw)
    if kind is int:
        try:
            return round(float(raw))
        except (TypeError, ValueError):
            return fallback
    if kind is float:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return fallback
    text = str(raw if raw is not None else "").strip()
    return text or EMPTY_DEFAULTS.get(name, "")


# Qt keys that the hotkey parser knows by name (hotkeys.NAMED_KEYS), for the
# press-to-set fields.
_NAMED_QT_KEYS = {
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Escape: "esc",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Pause: "pause",
    Qt.Key.Key_ScrollLock: "scrolllock",
    Qt.Key.Key_Print: "printscreen",
}


def combo_from_key(key: int, modifiers: int) -> str:
    """The hotkey text for a Qt key press ('ctrl+shift+t'), or '' for a
    press of modifiers alone or of a key the parser cannot register."""
    key = int(key)
    mods = Qt.KeyboardModifier(modifiers)
    parts = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        parts.append("ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        parts.append("alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        parts.append("shift")
    if mods & Qt.KeyboardModifier.MetaModifier:
        parts.append("win")
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        name = chr(key).lower()
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        name = f"f{key - Qt.Key.Key_F1 + 1}"
    else:
        name = _NAMED_QT_KEYS.get(key)  # type: ignore[call-overload]
        if name is None:
            return ""
    return "+".join([*parts, name])


class OfflineDownloadThread(QThread):
    """Fetches the offline translator's runtime and the model for a pair."""

    progress = Signal(str)
    finished_ok = Signal(bool, str)

    def __init__(self, source: str, target: str, store: ProfileStore, parent=None) -> None:
        super().__init__(parent)
        self.source, self.target, self.store = source, target, store

    def run(self) -> None:
        from ..translate.offline import ensure_offline

        try:
            model_dir = ensure_offline(
                self.source, self.target, self.store.models_dir, self.store.runtime_dir, self.progress.emit
            )
        except Exception as exc:  # reported in the window
            self.finished_ok.emit(False, f"download failed: {exc}")
            return
        self.finished_ok.emit(True, f"offline translation ready: {model_dir}")


class SettingsBackend(QObject):
    # To the tray, which owns the controller.
    applied = Signal(object, object)  # Settings, hwnd or None: run the overlay with these
    settings_changed = Signal(object)  # Settings: an edit, once the typing has paused; a running overlay follows it
    stop_requested = Signal()
    select_area_requested = Signal()
    profile_saved = Signal(str)
    profile_loaded = Signal(str, object)  # name, Settings
    hotkeys_changed = Signal(object)  # Settings: register these hotkeys now
    hotkey_capture_changed = Signal(bool)  # True while a field records a key press: release the global hotkeys
    remove_all_data_requested = Signal()  # the user confirmed: wipe everything and quit

    # To the QML pages.
    statusChanged = Signal()
    statusTextChanged = Signal()
    profileNameChanged = Signal()
    profilesChanged = Signal()
    windowsChanged = Signal()
    keyStatusChanged = Signal()
    licenseTextChanged = Signal()
    downloadChanged = Signal()
    problemChanged = Signal()

    def __init__(
        self,
        settings: Settings,
        store: ProfileStore,
        secrets: SecretStore | None = None,
        profile_name: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.secrets: SecretStore = secrets if secrets is not None else WindowsCredentialStore()
        with warnings.catch_warnings():  # PySide6 6.12 flags the one public constructor as deprecated
            warnings.simplefilter("ignore", DeprecationWarning)
            self._map = QQmlPropertyMap()
        self._base: Settings
        self._status = "idle"
        self._status_text = ""
        self._profile_name = profile_name or ""
        self._windows: dict[str, int] = {}  # title -> hwnd, from the last refresh
        self._license_text = ""
        self._download: OfflineDownloadThread | None = None
        self._download_status = ""
        self._problem = ""
        self._edit_problem = False  # the banner shows a problem an edit caused (cleared once corrected)
        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(EDIT_DELAY_MS)
        self._edit_timer.timeout.connect(self._emit_edit)
        self.load(settings)
        self._map.valueChanged.connect(self._on_value_changed)
        self._refresh_license_status()

    # -- settings <-> map ---------------------------------------------------------

    def load(self, settings: Settings) -> None:
        """Show `settings`; they become the base `to_settings()` builds on.
        (Writes from Python do not count as edits: no hotkey registration.)"""
        self._base = settings
        for name in _FIELDS:
            value = getattr(settings, name)
            self._map.insert(name, "\n".join(value) if name in LIST_FIELDS else value)
        for name in DEFAULT_HOTKEYS:
            self._map.insert(f"hotkey_{name}", settings.hotkeys.get(name, DEFAULT_HOTKEYS[name]))

    def to_settings(self, base: Settings | None = None) -> Settings:
        """The map's values on top of `base` (default: the settings last
        loaded), so fields the window does not show keep their values."""
        s = (base if base is not None else self._base).copy()
        for name in _FIELDS:
            raw = self._map.value(name)
            if name in LIST_FIELDS:
                setattr(s, name, _lines(raw))
            else:
                setattr(s, name, _coerce(name, raw, getattr(s, name)))
        s.hotkeys = {
            name: (str(self._map.value(f"hotkey_{name}") or "").strip() or DEFAULT_HOTKEYS[name])
            for name in DEFAULT_HOTKEYS
        }
        return s

    def set(self, name: str, value: Any) -> None:
        """Change one entry as an edit from a page would: the same follow-up
        (the map's own valueChanged reports QML writes only)."""
        self._map.insert(name, value)
        self._on_value_changed(name, value)

    def _on_value_changed(self, key: str, _value: Any) -> None:
        if key.startswith("hotkey_"):
            self.hotkeys_changed.emit(self.to_settings())
        else:
            self._edit_timer.start()

    def _emit_edit(self) -> None:
        """The typing has paused: the settings go out if they are valid; a
        problem shows in the banner until the edit is corrected."""
        settings = self.to_settings()
        problem = invalid_pattern(settings.ignore_patterns) or invalid_hotkey(settings.hotkeys)
        if problem:
            self._edit_problem = True
            self.report_problem(problem)
            return
        if self._edit_problem:
            self._edit_problem = False
            self.clearProblem()
        self.settings_changed.emit(settings)

    def _checked_settings(self) -> Settings | None:
        """The map's settings when they can run, else None with the problem reported."""
        settings = self.to_settings()
        problem = invalid_pattern(settings.ignore_patterns) or invalid_hotkey(settings.hotkeys)
        if problem:
            self.report_problem(problem)
            return None
        return settings

    def _settings_map(self) -> QObject:
        return self._map

    settings = Property(QObject, _settings_map, constant=True)

    # -- constants for the pages --------------------------------------------------------

    appName = Property(str, lambda self: APP_NAME, constant=True)
    version = Property(str, lambda self: __version__, constant=True)
    ocrLangs = Property("QStringList", lambda self: list(OCR_LANGS), constant=True)
    claudeModels = Property("QStringList", lambda self: list(CLAUDE_MODELS), constant=True)
    trialDays = Property(int, lambda self: TRIAL_DAYS, constant=True)
    purchaseUrl = Property(str, lambda self: PURCHASE_URL, constant=True)
    dataFolder = Property(str, lambda self: str(self.store.root), constant=True)
    dataDescription = Property(str, lambda self: describe_data(self.store, self.secrets), constant=True)
    hotkeyNames = Property("QStringList", lambda self: list(DEFAULT_HOTKEYS), constant=True)  # in menu order
    defaultHotkeys = Property("QVariantMap", lambda self: dict(DEFAULT_HOTKEYS), constant=True)
    hotkeyLabels = Property("QVariantMap", lambda self: dict(HOTKEY_LABELS), constant=True)

    def _font_families(self) -> list[str]:
        """The fonts on this computer, for the Appearance page ("@" names
        are Windows' vertical variants)."""
        if QGuiApplication.instance() is None:
            return []
        return [name for name in QFontDatabase.families() if not name.startswith("@")]

    fontFamilies = Property("QStringList", _font_families, constant=True)

    # -- overlay state -------------------------------------------------------------------

    def _get_status(self) -> str:
        return self._status

    def set_status(self, running: bool, starting: bool = False, paused: bool = False) -> None:
        status = "starting" if starting else "paused" if running and paused else "running" if running else "idle"
        if status != self._status:
            self._status = status
            self.statusChanged.emit()

    def _get_status_text(self) -> str:
        return self._status_text

    def set_status_text(self, text: str) -> None:
        if text != self._status_text:
            self._status_text = text
            self.statusTextChanged.emit()

    status = Property(str, _get_status, notify=statusChanged)
    statusText = Property(str, _get_status_text, notify=statusTextChanged)

    @Slot()
    def start(self) -> None:
        """Validate, then ask the tray to run the overlay with the map's settings."""
        settings = self._checked_settings()
        if settings is not None:
            self.applied.emit(settings, self.selected_hwnd())

    @Slot()
    def stop(self) -> None:
        self.stop_requested.emit()

    # -- game window ------------------------------------------------------------------------

    def _get_windows(self) -> list[str]:
        return list(self._windows)

    windows = Property("QStringList", _get_windows, notify=windowsChanged)

    @Slot()
    def refreshWindows(self) -> None:
        try:
            from ..capture.windows import list_windows

            found = list_windows()
        except Exception:  # not on Windows, or no desktop session
            found = []
        self._windows = {w.title: w.hwnd for w in sorted(found, key=lambda w: w.title.casefold()) if w.title}
        self.windowsChanged.emit()

    def selected_hwnd(self) -> int | None:
        """The handle of the listed window whose title the map names
        exactly, or None when the text is a substring to match instead."""
        return self._windows.get(str(self._map.value("window_match") or "").strip())

    @Slot()
    def selectArea(self) -> None:
        self.select_area_requested.emit()

    @Slot()
    def useBottomStrip(self) -> None:
        self.set("roi", BOTTOM_STRIP)

    @Slot()
    def useWholeWindow(self) -> None:
        self.set("roi", "")

    # -- profiles ---------------------------------------------------------------------------

    def _get_profile_name(self) -> str:
        return self._profile_name

    def set_profile_name(self, name: str) -> None:
        if name != self._profile_name:
            self._profile_name = name
            self.profileNameChanged.emit()

    def _get_profiles(self) -> list[str]:
        return self.store.list()

    profileName = Property(str, _get_profile_name, notify=profileNameChanged)
    profiles = Property("QStringList", _get_profiles, notify=profilesChanged)

    @Slot(str)
    def saveProfile(self, name: str) -> None:
        settings = self._checked_settings()
        if settings is None:
            return
        name = slug(name.strip() or settings.game or settings.window_match or "game")
        self.store.save(name, settings)
        self.store.last_profile = name
        self._base = settings
        self.set_profile_name(name)
        self.profilesChanged.emit()
        self.profile_saved.emit(name)

    @Slot(str)
    def loadProfile(self, name: str) -> None:
        try:
            settings = self.store.load(name)
        except (OSError, ValueError) as exc:
            self.report_problem(f"Could not load profile {name}: {exc}")
            return
        self.load(settings)
        self.store.last_profile = name
        self.set_profile_name(name)
        self.profile_loaded.emit(name, settings)

    # -- API keys -------------------------------------------------------------------------------

    def _deepl_key_status(self) -> str:
        return key_status(DEEPL_KEY, self.secrets)

    def _anthropic_key_status(self) -> str:
        return key_status(ANTHROPIC_KEY, self.secrets)

    deeplKeyStatus = Property(str, _deepl_key_status, notify=keyStatusChanged)
    anthropicKeyStatus = Property(str, _anthropic_key_status, notify=keyStatusChanged)

    @Slot(str, str)
    def saveKey(self, name: str, value: str) -> None:
        """Store a key; the field that held it is blanked by the page."""
        value = value.strip()
        if name not in (DEEPL_KEY, ANTHROPIC_KEY) or not value:
            return
        self.secrets.set(name, value)
        self.keyStatusChanged.emit()

    @Slot(str)
    def clearKey(self, name: str) -> None:
        if name in (DEEPL_KEY, ANTHROPIC_KEY):
            self.secrets.delete(name)
            self.keyStatusChanged.emit()

    # -- licence ------------------------------------------------------------------------------------

    def _get_license_text(self) -> str:
        return self._license_text

    licenseText = Property(str, _get_license_text, notify=licenseTextChanged)

    def _refresh_license_status(self) -> None:
        self._set_license_text(license_status(self.secrets, self.store).text)

    def _set_license_text(self, text: str) -> None:
        if text != self._license_text:
            self._license_text = text
            self.licenseTextChanged.emit()

    @Slot(str)
    def activateLicense(self, key: str) -> None:
        key = key.strip()
        if not key:
            return
        try:
            activate(key, self.secrets)
        except LicenseError as exc:
            self._set_license_text(f"key rejected: {exc}")
            return
        self._refresh_license_status()

    @Slot()
    def removeLicense(self) -> None:
        deactivate(self.secrets)
        self._refresh_license_status()

    # -- data ------------------------------------------------------------------------------------------

    @Slot()
    def openDataFolder(self) -> None:
        self.store.root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))

    @Slot()
    def removeAllData(self) -> None:
        """The page has asked for confirmation; the tray stops the overlay,
        deletes everything and quits."""
        self.remove_all_data_requested.emit()

    # -- offline translation ----------------------------------------------------------------------------

    def _get_download_status(self) -> str:
        return self._download_status

    def _get_downloading(self) -> bool:
        return self._download is not None and self._download.isRunning()

    downloadStatus = Property(str, _get_download_status, notify=downloadChanged)
    downloading = Property(bool, _get_downloading, notify=downloadChanged)

    @Slot()
    def downloadOffline(self) -> None:
        """Fetch the offline translator (its runtime, once) and the model for the language pair."""
        if self._get_downloading():
            return
        settings = self.to_settings()
        source, target = settings.effective_source_lang, settings.target_lang
        thread = OfflineDownloadThread(source, target, self.store, self)
        thread.progress.connect(self._set_download_status)
        thread.finished_ok.connect(self._download_done)
        thread.finished.connect(self.downloadChanged)  # `downloading` turns false once the thread has ended
        thread.finished.connect(thread.deleteLater)
        self._download = thread
        thread.start()
        self._set_download_status(f"downloading offline translation for {source} -> {target}...")

    def _set_download_status(self, text: str) -> None:
        self._download_status = text
        self.downloadChanged.emit()

    def _download_done(self, ok: bool, message: str) -> None:
        if ok and not self._map.value("draft"):
            self.set("draft", "offline")
        self._set_download_status(message)

    # -- glossary -----------------------------------------------------------------------------------------

    @Slot()
    def browseGlossary(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(None, "Glossary JSON", "", "JSON (*.json)")
        if path:
            self.set("glossary_path", path)

    # -- hotkeys ------------------------------------------------------------------------------------------

    @Slot(int, int, result=str)
    def comboFromKey(self, key: int, modifiers: int) -> str:
        return combo_from_key(key, modifiers)

    @Slot(bool)
    def setHotkeyCapture(self, capturing: bool) -> None:
        self.hotkey_capture_changed.emit(capturing)

    @Slot()
    def resetHotkeys(self) -> None:
        for name, combo in DEFAULT_HOTKEYS.items():
            self.set(f"hotkey_{name}", combo)

    # -- problems ------------------------------------------------------------------------------------------

    def _get_problem(self) -> str:
        return self._problem

    problem = Property(str, _get_problem, notify=problemChanged)

    def report_problem(self, text: str) -> None:
        self._problem = text
        self.problemChanged.emit()

    @Slot()
    def clearProblem(self) -> None:
        if self._problem:
            self._problem = ""
            self.problemChanged.emit()


def qml_dir() -> Path:
    return Path(__file__).resolve().parent / "qml"
