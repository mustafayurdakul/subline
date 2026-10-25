"""Settings window: pick the game window, languages, translator, appearance,
ignores and hotkeys; apply at once or save as a per-game profile."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..capture.windows import list_windows
from .cleanup import describe_data
from .config import DEFAULT_HOTKEYS, ProfileStore, Settings, slug
from .credentials import ANTHROPIC_KEY, DEEPL_KEY, SecretStore, WindowsCredentialStore, key_status
from .license import PURCHASE_URL, TRIAL_DAYS, LicenseError, activate, deactivate, license_status

# fmt: off
OCR_LANGS = [
    "en", "ch", "chinese_cht", "japan", "korean", "de", "fr", "es", "it", "pt", "pl", "nl", "tr", "cyrillic", "arabic",
]
# fmt: on
TRANSLATORS = ["claude", "deepl", "offline", "uppercase", "echo", "verbose"]
CLAUDE_MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
HOTKEY_LABELS = {
    "toggle": "Start / stop overlay",
    "pause": "Pause / resume",
    "rescan": "Rescan screen",
    "select": "Select area to translate",
    "settings": "Open settings",
}


def _lines(widget: QPlainTextEdit) -> list[str]:
    return [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]


def invalid_pattern(patterns: list[str]) -> str | None:
    """One line naming the first ignore pattern that is not a valid regular
    expression, or None when all compile."""
    for pattern in patterns:
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"Ignore pattern {pattern!r} is not a valid regular expression: {exc}"
    return None


def _row(*widgets: QWidget) -> QHBoxLayout:
    """A field followed by its buttons, the field taking the spare width."""
    row = QHBoxLayout()
    for index, widget in enumerate(widgets):
        row.addWidget(widget, 1 if index == 0 else 0)
    return row


class ModelDownloadThread(QThread):
    progress = Signal(str)
    finished_ok = Signal(bool, str)

    def __init__(self, source: str, target: str, models_dir, parent=None) -> None:
        super().__init__(parent)
        self.source, self.target, self.models_dir = source, target, models_dir

    def run(self) -> None:
        from ..translate.offline import ensure_model

        try:
            model_dir, _ = ensure_model(self.source, self.target, self.models_dir, self.progress.emit)
        except Exception as exc:  # reported in the dialog
            self.finished_ok.emit(False, f"download failed: {exc}")
            return
        self.finished_ok.emit(True, f"offline model ready: {model_dir}")


class SettingsDialog(QDialog):
    applied = Signal(object, object)  # Settings, hwnd or None
    profile_saved = Signal(str)
    select_area_requested = Signal()
    remove_all_data_requested = Signal()  # the user confirmed: wipe everything and quit

    def __init__(
        self,
        settings: Settings,
        store: ProfileStore,
        secrets: SecretStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("gametl settings")
        self.setMinimumWidth(560)
        self.store = store
        self.secrets: SecretStore = secrets if secrets is not None else WindowsCredentialStore()
        self._download: ModelDownloadThread | None = None
        # The settings last loaded: fields without a widget (command-line
        # only: stable_frames, max_missing, debug, ...) are carried over from
        # it, so Apply and Save never reset them.
        self._base: Settings = settings
        self._build()
        self.load_settings(settings)

    # -- widgets -------------------------------------------------------------

    def _build(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._game_tab(), "Game")
        tabs.addTab(self._translation_tab(), "Translation")
        tabs.addTab(self._appearance_tab(), "Appearance")
        tabs.addTab(self._hotkeys_tab(), "Hotkeys")
        tabs.addTab(self._license_tab(), "Licence")

        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("profile name (default: game name)")
        save_btn = QPushButton("Save profile")
        save_btn.clicked.connect(self.save_profile)
        profile_row = _row(self.profile_name, save_btn)
        profile_row.insertWidget(0, QLabel("Profile"))

        buttons = QDialogButtonBox()
        apply_btn = buttons.addButton("Apply and run", QDialogButtonBox.ButtonRole.AcceptRole)
        close_btn = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        apply_btn.clicked.connect(self.apply)
        close_btn.clicked.connect(self.close)

        root = QVBoxLayout(self)
        root.addWidget(tabs)
        root.addLayout(profile_row)
        root.addWidget(buttons)

    def _game_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.window_combo = QComboBox()
        self.window_combo.setEditable(True)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_windows)
        form.addRow("Game window", _row(self.window_combo, refresh))
        self.game = QLineEdit()
        self.game.setPlaceholderText("name used in the prompt and cache; default: window title")
        form.addRow("Game name", self.game)
        self.roi = QLineEdit()
        self.roi.setPlaceholderText("x,y,w,h as fractions, e.g. 0,0.75,1,0.25; empty = whole window")
        select_btn = QPushButton("Select on screen")
        select_btn.setToolTip("Drag a rectangle over the game (also the Select hotkey)")
        select_btn.clicked.connect(self.select_area_requested.emit)
        form.addRow("Area to translate", _row(self.roi, select_btn))
        self.ignore_zones = QPlainTextEdit()
        self.ignore_zones.setPlaceholderText("one zone per line, x,y,w,h as fractions of the client area")
        self.ignore_zones.setFixedHeight(70)
        form.addRow("Ignore zones", self.ignore_zones)
        self.ignore_patterns = QPlainTextEdit()
        self.ignore_patterns.setPlaceholderText(
            "one regex per line (case-insensitive), e.g. ^[^a-z]+$ drops lines without letters"
        )
        self.ignore_patterns.setFixedHeight(70)
        form.addRow("Ignore patterns", self.ignore_patterns)
        self.include_frame = QCheckBox("read the title bar and window frame too")
        form.addRow("", self.include_frame)
        self.hide_when_unfocused = QCheckBox("hide the overlay when the game is not in front")
        form.addRow("", self.hide_when_unfocused)
        self.exclude_from_capture = QCheckBox("keep the overlay out of screen recordings, streams and screenshots")
        form.addRow("", self.exclude_from_capture)
        self.refresh_windows()
        return page

    def _translation_tab(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        form = QFormLayout()
        self.lang = QComboBox()
        self.lang.setEditable(True)
        self.lang.addItems(OCR_LANGS)
        form.addRow("OCR language", self.lang)
        self.ocr_gpu = QCheckBox("run OCR on the GPU (DirectML)")
        self.ocr_gpu.setToolTip(
            "Faster for large areas (a full frame read in half the time); slower than the CPU on a small "
            "subtitle strip. Any DirectX 12 graphics card."
        )
        form.addRow("", self.ocr_gpu)
        self.source_lang = QLineEdit()
        self.source_lang.setPlaceholderText("default: same as OCR language")
        form.addRow("Source language", self.source_lang)
        self.target_lang = QLineEdit()
        form.addRow("Target language", self.target_lang)
        self.translator = QComboBox()
        self.translator.addItems(TRANSLATORS)
        self.translator.setToolTip("deepl and claude need their API key entered below (DeepL has a free tier)")
        form.addRow("Translator", self.translator)
        self.draft = QComboBox()
        self.draft.addItems(["none", "offline", "deepl"])
        self.draft.setToolTip(
            "Show a fast draft, replaced when the translator answers: "
            "offline needs the downloaded model, deepl needs its key."
        )
        self.download_btn = QPushButton("Download offline model")
        self.download_btn.clicked.connect(self.download_model)
        form.addRow("Draft", _row(self.draft, self.download_btn))
        self.download_status = QLabel("")
        self.download_status.setWordWrap(True)
        form.addRow("", self.download_status)
        self.use_cache_file = QCheckBox("remember translations per game on disk")
        form.addRow("", self.use_cache_file)
        column.addLayout(form)

        keys = QGroupBox("API keys (kept in Windows Credential Manager, never in profiles)")
        form = QFormLayout(keys)
        self.key_edits: dict[str, QLineEdit] = {}
        self.key_labels: dict[str, QLabel] = {}
        for name, label in ((DEEPL_KEY, "DeepL key"), (ANTHROPIC_KEY, "Anthropic key")):
            edit = QLineEdit()
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setPlaceholderText("paste the key, then Save (Apply saves it too)")
            save = QPushButton("Save")
            save.clicked.connect(lambda _checked=False, n=name: self.save_key(n))
            clear = QPushButton("Clear")
            clear.clicked.connect(lambda _checked=False, n=name: self.clear_key(n))
            status = QLabel("")
            self.key_edits[name] = edit
            self.key_labels[name] = status
            form.addRow(label, _row(edit, save, clear))
            form.addRow("", status)
        column.addWidget(keys)
        self._refresh_key_status()

        claude = QGroupBox("Claude")
        form = QFormLayout(claude)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(CLAUDE_MODELS)
        form.addRow("Model", self.model)
        self.effort = QComboBox()
        self.effort.addItems(["low", "medium", "high"])
        form.addRow("Effort", self.effort)
        self.thinking = QComboBox()
        self.thinking.addItems(["disabled", "adaptive"])
        form.addRow("Thinking", self.thinking)
        self.structured = QCheckBox("server-side structured output (slower, guaranteed JSON)")
        form.addRow("", self.structured)
        self.glossary_path = QLineEdit()
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_glossary)
        form.addRow("Glossary (JSON)", _row(self.glossary_path, browse))
        self.tone = QLineEdit()
        self.tone.setPlaceholderText("notes on tone and formality (optional)")
        form.addRow("Tone notes", self.tone)
        column.addWidget(claude)
        column.addStretch(1)
        return page

    def _appearance_tab(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        form = QFormLayout()
        self.render = QComboBox()
        self.render.addItems(["subtitle", "inplace"])
        self.render.setToolTip(
            "subtitle: with an area selected, one fixed style centred in it. inplace: per block at the OCR box."
        )
        form.addRow("Render", self.render)
        self.font = QLineEdit()
        form.addRow("Font", self.font)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(1.0, 60.0)
        self.fps.setDecimals(0)
        form.addRow("Capture rate (fps)", self.fps)
        self.diff_threshold = QDoubleSpinBox()
        self.diff_threshold.setRange(0.0, 50.0)
        self.diff_threshold.setDecimals(1)
        self.diff_threshold.setSingleStep(0.5)
        self.diff_threshold.setSpecialValueText("off: read every frame")
        self.diff_threshold.setToolTip(
            "OCR is skipped while the read area looks the same as the frame last read (mean difference of a small "
            "grey thumbnail, 0-255). Lower it if a subtitle change is ever missed; 0 reads every frame."
        )
        form.addRow("Skip unchanged frames below", self.diff_threshold)
        column.addLayout(form)

        subtitle = QGroupBox("Subtitle mode (with an area selected)")
        form = QFormLayout(subtitle)
        self.subtitle_font_px = QSpinBox()
        self.subtitle_font_px.setRange(0, 200)
        self.subtitle_font_px.setSpecialValueText("game's own size")
        form.addRow("Font size (px)", self.subtitle_font_px)
        self.subtitle_color = QLineEdit()
        self.subtitle_color.setPlaceholderText("#FFFFFF")
        form.addRow("Text colour", self.subtitle_color)
        self.subtitle_background = QComboBox()
        self.subtitle_background.addItems(["pill", "none"])
        form.addRow("Background", self.subtitle_background)
        self.subtitle_position = QComboBox()
        self.subtitle_position.addItems(["source", "bottom", "center"])
        self.subtitle_position.setToolTip("source: where the game drew the line; bottom / center: of the selected area")
        form.addRow("Position", self.subtitle_position)
        self.subtitle_hide_source = QCheckBox("hide the original line when the subtitle is drawn elsewhere")
        form.addRow("", self.subtitle_hide_source)
        self.center_zone = QCheckBox("keep a selected area centred horizontally")
        form.addRow("", self.center_zone)
        column.addWidget(subtitle)

        inplace = QGroupBox("In-place mode")
        form = QFormLayout(inplace)
        self.style = QComboBox()
        self.style.addItems(["auto", "patch", "pill", "outline"])
        self.style.setToolTip("auto: patch the original out in its own colours, or a pill where the background is busy")
        form.addRow("Style", self.style)
        column.addWidget(inplace)
        column.addStretch(1)
        return page

    def _hotkeys_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.hotkey_edits: dict[str, QLineEdit] = {}
        for name, label in HOTKEY_LABELS.items():
            edit = QLineEdit()
            edit.setPlaceholderText(DEFAULT_HOTKEYS[name])
            self.hotkey_edits[name] = edit
            form.addRow(label, edit)
        form.addRow("", QLabel("Combinations like ctrl+shift+t, alt+f5. Changes apply on Apply."))
        return page

    def _license_tab(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        self.license_label = QLabel("")
        self.license_label.setWordWrap(True)
        column.addWidget(self.license_label)
        form = QFormLayout()
        self.license_key = QLineEdit()
        self.license_key.setPlaceholderText("paste your licence key (GAMETL-...)")
        activate_btn = QPushButton("Activate")
        activate_btn.clicked.connect(self.activate_license)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self.remove_license)
        form.addRow("Licence key", _row(self.license_key, activate_btn, remove_btn))
        column.addLayout(form)
        note = QLabel(
            f"Without a key gametl runs for a {TRIAL_DAYS}-day trial. "
            "The key is kept in Windows Credential Manager, never in a profile."
        )
        note.setWordWrap(True)
        column.addWidget(note)
        if PURCHASE_URL:
            link = QLabel(f'<a href="{PURCHASE_URL}">Buy a licence</a>')
            link.setOpenExternalLinks(True)
            column.addWidget(link)

        data = QGroupBox("Data on this computer")
        data_column = QVBoxLayout(data)
        self.data_label = QLabel(describe_data(self.store, self.secrets))
        self.data_label.setWordWrap(True)
        self.data_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        data_column.addWidget(self.data_label)
        self.remove_data_btn = QPushButton("Remove all data and quit")
        self.remove_data_btn.setToolTip(
            "Deletes the folder and the Credential Manager entries above (profiles, translation caches, "
            "downloaded models, API keys, licence key, trial start), then quits. Nothing of gametl stays on "
            "this computer apart from the program folder itself."
        )
        self.remove_data_btn.clicked.connect(self.remove_all_data)
        data_column.addWidget(self.remove_data_btn, 0, Qt.AlignmentFlag.AlignLeft)
        column.addWidget(data)
        column.addStretch(1)
        self._refresh_license_status()
        return page

    # -- actions ---------------------------------------------------------------

    def refresh_windows(self) -> None:
        current = self.window_combo.currentText()
        self.window_combo.clear()
        for w in sorted(list_windows(), key=lambda w: w.title.casefold()):
            self.window_combo.addItem(w.title, w.hwnd)
        if current:
            self.window_combo.setEditText(current)

    def selected_hwnd(self) -> int | None:
        """The handle of the listed window the combo shows, or None when the
        text was typed by hand (then the title substring is matched instead)."""
        index = self.window_combo.currentIndex()
        if index >= 0 and self.window_combo.itemText(index) == self.window_combo.currentText():
            data = self.window_combo.itemData(index)
            return int(data) if data else None
        return None

    def download_model(self) -> None:
        if self._download is not None and self._download.isRunning():
            return
        source = self.source_lang.text().strip() or self.lang.currentText().strip() or "en"
        target = self.target_lang.text().strip() or "tr"
        self.download_btn.setEnabled(False)
        self.download_status.setText(f"downloading offline model for {source} -> {target}...")
        self._download = ModelDownloadThread(source, target, self.store.models_dir, self)
        self._download.progress.connect(self.download_status.setText)
        self._download.finished_ok.connect(self._download_done)
        self._download.start()

    def _download_done(self, ok: bool, message: str) -> None:
        self.download_btn.setEnabled(True)
        self.download_status.setText(message)
        if ok and self.draft.currentText() == "none":
            self.draft.setCurrentText("offline")

    def _browse_glossary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Glossary JSON", "", "JSON (*.json)")
        if path:
            self.glossary_path.setText(path)

    # -- API keys ---------------------------------------------------------------

    def save_key(self, name: str) -> None:
        """Store what was typed for `name` and blank the field, so the key
        stays in a widget no longer than needed."""
        value = self.key_edits[name].text().strip()
        if not value:
            return
        self.secrets.set(name, value)
        self.key_edits[name].clear()
        self._refresh_key_status()

    def save_typed_keys(self) -> None:
        for name in self.key_edits:
            self.save_key(name)

    def clear_key(self, name: str) -> None:
        self.secrets.delete(name)
        self.key_edits[name].clear()
        self._refresh_key_status()

    def _refresh_key_status(self) -> None:
        for name, label in self.key_labels.items():
            label.setText(key_status(name, self.secrets))

    # -- licence ----------------------------------------------------------------

    def activate_license(self) -> None:
        key = self.license_key.text().strip()
        if not key:
            return
        try:
            activate(key, self.secrets)
        except LicenseError as exc:
            self.license_label.setText(f"key rejected: {exc}")
            return
        self.license_key.clear()
        self._refresh_license_status()

    def remove_license(self) -> None:
        deactivate(self.secrets)
        self.license_key.clear()
        self._refresh_license_status()

    def _refresh_license_status(self) -> None:
        self.license_label.setText(license_status(self.secrets, self.store).text)

    # -- data removal -------------------------------------------------------------

    def confirm_remove_all_data(self) -> bool:
        answer = QMessageBox.warning(
            self,
            "gametl",
            "Remove every profile, translation cache, downloaded model, the API keys, the licence key and "
            "the trial record from this computer, then quit?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def remove_all_data(self) -> None:
        """Ask once, then hand the removal to the owner (the tray), which
        stops the overlay, deletes everything and quits."""
        if self.confirm_remove_all_data():
            self.remove_all_data_requested.emit()

    # -- settings <-> widgets -------------------------------------------------------

    def load_settings(self, s: Settings) -> None:
        self._base = s
        self.window_combo.setEditText(s.window_match)
        self.game.setText(s.game)
        self.roi.setText(s.roi)
        self.ignore_zones.setPlainText("\n".join(s.ignore_zones))
        self.ignore_patterns.setPlainText("\n".join(s.ignore_patterns))
        self.include_frame.setChecked(s.include_frame)
        self.hide_when_unfocused.setChecked(s.hide_when_unfocused)
        self.exclude_from_capture.setChecked(s.exclude_from_capture)
        self.lang.setEditText(s.lang)
        self.ocr_gpu.setChecked(s.ocr_gpu)
        self.source_lang.setText(s.source_lang)
        self.target_lang.setText(s.target_lang)
        self.translator.setCurrentText(s.translator)
        self.draft.setCurrentText(s.draft or "none")
        self.model.setEditText(s.model)
        self.effort.setCurrentText(s.effort)
        self.thinking.setCurrentText(s.thinking)
        self.structured.setChecked(s.structured)
        self.glossary_path.setText(s.glossary_path)
        self.tone.setText(s.tone)
        self.use_cache_file.setChecked(s.use_cache_file)
        self.style.setCurrentText(s.style)
        self.render.setCurrentText(s.render)
        self.subtitle_font_px.setValue(s.subtitle_font_px)
        self.subtitle_color.setText(s.subtitle_color)
        self.subtitle_background.setCurrentText(s.subtitle_background)
        self.subtitle_position.setCurrentText(s.subtitle_position)
        self.subtitle_hide_source.setChecked(s.subtitle_hide_source)
        self.center_zone.setChecked(s.center_zone)
        self.font.setText(s.font)
        self.fps.setValue(s.fps)
        self.diff_threshold.setValue(s.diff_threshold)
        for name, edit in self.hotkey_edits.items():
            edit.setText(s.hotkeys.get(name, DEFAULT_HOTKEYS[name]))

    def to_settings(self, base: Settings | None = None) -> Settings:
        """The widgets' values on top of `base` (default: the settings last
        loaded), so fields the dialog does not show keep their values."""
        s = (base if base is not None else self._base).copy()
        s.window_match = self.window_combo.currentText().strip()
        s.game = self.game.text().strip()
        s.roi = self.roi.text().strip()
        s.ignore_zones = _lines(self.ignore_zones)
        s.ignore_patterns = _lines(self.ignore_patterns)
        s.include_frame = self.include_frame.isChecked()
        s.hide_when_unfocused = self.hide_when_unfocused.isChecked()
        s.exclude_from_capture = self.exclude_from_capture.isChecked()
        s.lang = self.lang.currentText().strip() or "en"
        s.ocr_gpu = self.ocr_gpu.isChecked()
        s.source_lang = self.source_lang.text().strip()
        s.target_lang = self.target_lang.text().strip() or "tr"
        s.translator = self.translator.currentText()
        s.draft = "" if self.draft.currentText() == "none" else self.draft.currentText()
        s.model = self.model.currentText().strip() or CLAUDE_MODELS[0]
        s.effort = self.effort.currentText()
        s.thinking = self.thinking.currentText()
        s.structured = self.structured.isChecked()
        s.glossary_path = self.glossary_path.text().strip()
        s.tone = self.tone.text().strip()
        s.use_cache_file = self.use_cache_file.isChecked()
        s.style = self.style.currentText()
        s.render = self.render.currentText()
        s.subtitle_font_px = self.subtitle_font_px.value()
        s.subtitle_color = self.subtitle_color.text().strip() or "#FFFFFF"
        s.subtitle_background = self.subtitle_background.currentText()
        s.subtitle_position = self.subtitle_position.currentText()
        s.subtitle_hide_source = self.subtitle_hide_source.isChecked()
        s.center_zone = self.center_zone.isChecked()
        s.font = self.font.text().strip() or "Segoe UI"
        s.fps = float(self.fps.value())
        s.diff_threshold = float(self.diff_threshold.value())
        s.hotkeys = {name: (edit.text().strip() or DEFAULT_HOTKEYS[name]) for name, edit in self.hotkey_edits.items()}
        return s

    def report_problem(self, text: str) -> None:
        QMessageBox.warning(self, "gametl", text)

    def _valid(self) -> bool:
        problem = invalid_pattern(_lines(self.ignore_patterns))
        if problem:
            self.report_problem(problem)
            return False
        return True

    def apply(self) -> None:
        if not self._valid():
            return
        self.save_typed_keys()
        self.applied.emit(self.to_settings(), self.selected_hwnd())

    def save_profile(self) -> None:
        if not self._valid():
            return
        self.save_typed_keys()
        settings = self.to_settings()
        name = self.profile_name.text().strip() or settings.game or settings.window_match or "game"
        self.store.save(name, settings)
        self.store.last_profile = slug(name)
        self.profile_saved.emit(slug(name))
