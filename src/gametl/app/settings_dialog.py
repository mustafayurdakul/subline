"""Settings window: pick the game window, languages, translator, appearance,
ignores and hotkeys; apply at once or save as a per-game profile."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..capture.windows import list_windows
from .config import DEFAULT_HOTKEYS, ProfileStore, Settings, slug

OCR_LANGS = ["en", "ch", "chinese_cht", "japan", "korean", "de", "fr", "es", "it", "pt", "pl", "nl", "tr", "cyrillic", "arabic"]


def _lines(widget: QPlainTextEdit) -> list[str]:
    return [ln.strip() for ln in widget.toPlainText().splitlines() if ln.strip()]


class SettingsDialog(QDialog):
    applied = Signal(object, object)  # Settings, hwnd or None
    profile_saved = Signal(str)

    def __init__(self, settings: Settings, store: ProfileStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("gametl settings")
        self.setMinimumWidth(520)
        self.store = store
        self._build()
        self.load_settings(settings)

    # -- widgets -------------------------------------------------------------

    def _build(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._game_tab(), "Game")
        tabs.addTab(self._translation_tab(), "Translation")
        tabs.addTab(self._appearance_tab(), "Appearance")
        tabs.addTab(self._hotkeys_tab(), "Hotkeys")

        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("profile name (default: game name)")
        save_btn = QPushButton("Save profile")
        save_btn.clicked.connect(self.save_profile)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile"))
        profile_row.addWidget(self.profile_name, 1)
        profile_row.addWidget(save_btn)

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
        row = QHBoxLayout()
        row.addWidget(self.window_combo, 1)
        row.addWidget(refresh)
        form.addRow("Game window", row)
        self.game = QLineEdit()
        self.game.setPlaceholderText("name used in the prompt and cache; default: window title")
        form.addRow("Game name", self.game)
        self.roi = QLineEdit()
        self.roi.setPlaceholderText("subtitle zone x,y,w,h as fractions, e.g. 0,0.75,1,0.25 (optional)")
        form.addRow("Subtitle zone", self.roi)
        self.ignore_zones = QPlainTextEdit()
        self.ignore_zones.setPlaceholderText("one zone per line, x,y,w,h as fractions of the client area")
        self.ignore_zones.setFixedHeight(70)
        form.addRow("Ignore zones", self.ignore_zones)
        self.ignore_patterns = QPlainTextEdit()
        self.ignore_patterns.setPlaceholderText("one regex per line, e.g. ^\\d+$")
        self.ignore_patterns.setFixedHeight(70)
        form.addRow("Ignore patterns", self.ignore_patterns)
        self.include_frame = QCheckBox("read the title bar and window frame too")
        form.addRow("", self.include_frame)
        self.hide_when_unfocused = QCheckBox("hide the overlay when the game is not in front")
        form.addRow("", self.hide_when_unfocused)
        self.refresh_windows()
        return page

    def _translation_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.lang = QComboBox()
        self.lang.setEditable(True)
        self.lang.addItems(OCR_LANGS)
        form.addRow("OCR language", self.lang)
        self.source_lang = QLineEdit()
        self.source_lang.setPlaceholderText("default: same as OCR language")
        form.addRow("Source language", self.source_lang)
        self.target_lang = QLineEdit()
        form.addRow("Target language", self.target_lang)
        self.translator = QComboBox()
        self.translator.addItems(["claude", "offline", "uppercase", "echo", "verbose"])
        form.addRow("Translator", self.translator)
        self.draft = QComboBox()
        self.draft.addItems(["none", "offline"])
        self.draft.setToolTip("Show an instant offline draft, replaced when the translator answers. Needs the offline model (gametl --download-model).")
        form.addRow("Draft", self.draft)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"])
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
        row = QHBoxLayout()
        row.addWidget(self.glossary_path, 1)
        row.addWidget(browse)
        form.addRow("Glossary (JSON)", row)
        self.tone = QLineEdit()
        self.tone.setPlaceholderText("notes on tone and formality (optional)")
        form.addRow("Tone notes", self.tone)
        self.use_cache_file = QCheckBox("remember translations per game on disk")
        form.addRow("", self.use_cache_file)
        return page

    def _appearance_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.style = QComboBox()
        self.style.addItems(["auto", "patch", "pill", "outline"])
        form.addRow("Style", self.style)
        self.font = QLineEdit()
        form.addRow("Font", self.font)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(1.0, 60.0)
        self.fps.setDecimals(0)
        form.addRow("Capture rate (fps)", self.fps)
        return page

    def _hotkeys_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.hotkey_edits: dict[str, QLineEdit] = {}
        labels = {"toggle": "Start / stop overlay", "pause": "Pause / resume", "rescan": "Rescan screen", "settings": "Open settings"}
        for name, label in labels.items():
            edit = QLineEdit()
            edit.setPlaceholderText(DEFAULT_HOTKEYS[name])
            self.hotkey_edits[name] = edit
            form.addRow(label, edit)
        form.addRow("", QLabel("Combinations like ctrl+shift+t, alt+f5. Changes apply on Apply."))
        return page

    # -- actions ---------------------------------------------------------------

    def refresh_windows(self) -> None:
        current = self.window_combo.currentText()
        self.window_combo.clear()
        for w in sorted(list_windows(), key=lambda w: w.title.casefold()):
            self.window_combo.addItem(f"{w.title}", w.hwnd)
        if current:
            self.window_combo.setEditText(current)

    def selected_hwnd(self) -> int | None:
        index = self.window_combo.currentIndex()
        if index >= 0 and self.window_combo.itemText(index) == self.window_combo.currentText():
            data = self.window_combo.itemData(index)
            return int(data) if data else None
        return None

    def _browse_glossary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Glossary JSON", "", "JSON (*.json)")
        if path:
            self.glossary_path.setText(path)

    def load_settings(self, s: Settings) -> None:
        self.window_combo.setEditText(s.window_match)
        self.game.setText(s.game)
        self.roi.setText(s.roi)
        self.ignore_zones.setPlainText("\n".join(s.ignore_zones))
        self.ignore_patterns.setPlainText("\n".join(s.ignore_patterns))
        self.include_frame.setChecked(s.include_frame)
        self.hide_when_unfocused.setChecked(s.hide_when_unfocused)
        self.lang.setEditText(s.lang)
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
        self.font.setText(s.font)
        self.fps.setValue(s.fps)
        for name, edit in self.hotkey_edits.items():
            edit.setText(s.hotkeys.get(name, DEFAULT_HOTKEYS[name]))

    def to_settings(self, base: Settings | None = None) -> Settings:
        s = (base or Settings()).copy()
        s.window_match = self.window_combo.currentText().strip()
        s.game = self.game.text().strip()
        s.roi = self.roi.text().strip()
        s.ignore_zones = _lines(self.ignore_zones)
        s.ignore_patterns = _lines(self.ignore_patterns)
        s.include_frame = self.include_frame.isChecked()
        s.hide_when_unfocused = self.hide_when_unfocused.isChecked()
        s.lang = self.lang.currentText().strip() or "en"
        s.source_lang = self.source_lang.text().strip()
        s.target_lang = self.target_lang.text().strip() or "tr"
        s.translator = self.translator.currentText()
        s.draft = "" if self.draft.currentText() == "none" else self.draft.currentText()
        s.model = self.model.currentText().strip() or "claude-haiku-5-5"
        s.effort = self.effort.currentText()
        s.thinking = self.thinking.currentText()
        s.structured = self.structured.isChecked()
        s.glossary_path = self.glossary_path.text().strip()
        s.tone = self.tone.text().strip()
        s.use_cache_file = self.use_cache_file.isChecked()
        s.style = self.style.currentText()
        s.font = self.font.text().strip() or "Segoe UI"
        s.fps = float(self.fps.value())
        s.hotkeys = {name: (edit.text().strip() or DEFAULT_HOTKEYS[name]) for name, edit in self.hotkey_edits.items()}
        return s

    def apply(self) -> None:
        self.applied.emit(self.to_settings(), self.selected_hwnd())

    def save_profile(self) -> None:
        settings = self.to_settings()
        name = self.profile_name.text().strip() or settings.game or settings.window_match or "game"
        self.store.save(name, settings)
        self.store.last_profile = slug(name)
        self.profile_saved.emit(slug(name))
