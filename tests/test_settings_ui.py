"""The settings window's QML behaves: what a page check cannot see, driven
through the real window and backend on the offscreen platform. Hotkey
capture ends with its page, drop-downs start from the value in force,
typed session fields are written once the typing is done, pages open at
their top, the scroll bar shows only when there is something to scroll,
a refused key stays in its field, and the window and its popups follow
the screen's scale."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QMetaObject, QObject, QPointF, QRect, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtTest import QTest

from gametl.app.config import ProfileStore, Settings
from gametl.app.credentials import MemorySecretStore
from gametl.app.settings_backend import TARGET_LANGUAGES, SettingsBackend
from gametl.app.settings_window import SettingsWindow


def settle(qapp, rounds: int = 20) -> None:
    for _ in range(rounds):
        qapp.processEvents()


def find(view: SettingsWindow, type_name: str, **props) -> list[QObject]:
    """The window's objects of QML type `type_name` whose properties match `props`."""
    return [
        obj
        for obj in view.objects()
        if obj.metaObject().className().startswith(f"{type_name}_QML")
        and all(obj.property(name) == value for name, value in props.items())
    ]


def press(qapp, view: SettingsWindow, key: Qt.Key, text: str = "", modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    """A key press and release, as the keyboard would send them to the focused item."""
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QGuiApplication.sendEvent(view, QKeyEvent(kind, key, modifiers, text))
    settle(qapp, 5)


def drawn(item: QObject) -> QRectF:
    """Where `item` is drawn in the window, in window pixels (its own and its parents' scale counted)."""
    return item.mapRectToScene(QRectF(0, 0, item.width(), item.height()))


def variant(value):
    """A JavaScript value as Python: an object arrives as a QJSValue or already converted."""
    return value.toVariant() if hasattr(value, "toVariant") else value or {}


def type_text(qapp, view: SettingsWindow, text: str) -> None:
    for letter in text:
        press(qapp, view, getattr(Qt.Key, f"Key_{letter.upper()}"), letter)


def open_window(qapp, tmp_path: Path, settings: Settings, scale: float | None = 1.0) -> SettingsWindow:
    backend = SettingsBackend(settings, ProfileStore(tmp_path), MemorySecretStore())
    view = SettingsWindow(backend, scale=scale)
    view.show()
    view.requestActivate()
    settle(qapp)
    assert view.problems == []
    return view


def close_window(qapp, view: SettingsWindow) -> None:
    view.close()
    view.setSource(QUrl())
    settle(qapp, 5)


@pytest.fixture
def window(qapp, tmp_path: Path) -> Iterator[SettingsWindow]:
    view = open_window(qapp, tmp_path, Settings(window_match="Fake Game", target_lang="de"))
    yield view
    close_window(qapp, view)


def test_hotkey_capture_ends_when_its_page_goes(qapp, window: SettingsWindow) -> None:
    """A click on another page takes no focus, it only unloads the field:
    the global hotkeys must come back all the same."""
    captures: list[bool] = []
    window.backend.hotkey_capture_changed.connect(captures.append)
    window.show_page("hotkeys")
    settle(qapp)
    (field,) = find(window, "HotkeyField", key="hotkey_toggle")
    QMetaObject.invokeMethod(field, "forceActiveFocus")
    settle(qapp)
    assert captures == [True]
    window.show_page("game")
    settle(qapp)
    assert captures == [True, False]


def test_hotkey_field_lets_tab_move_on(qapp, window: SettingsWindow) -> None:
    window.show_page("hotkeys")
    settle(qapp)
    (field,) = find(window, "HotkeyField", key="hotkey_toggle")
    QMetaObject.invokeMethod(field, "forceActiveFocus")
    settle(qapp)
    press(qapp, window, Qt.Key.Key_Tab)
    assert window.backend.settings.value("hotkey_toggle") == "ctrl+shift+t"  # not bound to Tab
    assert not field.property("activeFocus")


def test_a_drop_down_starts_from_the_value_in_force(qapp, window: SettingsWindow) -> None:
    codes = [code for code, _ in TARGET_LANGUAGES]
    (combo,) = find(window, "Combo", key="target_lang")
    assert combo.property("currentIndex") == codes.index("de")
    window.backend.set("target_lang", "ja")
    settle(qapp)
    assert combo.property("currentIndex") == codes.index("ja")
    QMetaObject.invokeMethod(combo, "forceActiveFocus")
    press(qapp, window, Qt.Key.Key_Down)
    assert window.backend.settings.value("target_lang") == codes[codes.index("ja") + 1]  # the next, not the second


def test_typed_session_fields_are_written_when_the_typing_is_done(qapp, window: SettingsWindow) -> None:
    """The game name restarts a running overlay: half a name must not."""
    window.show_page("game")
    settle(qapp)
    (field,) = find(window, "Field", key="game")
    QMetaObject.invokeMethod(field, "forceActiveFocus")
    for letter in "Ab":
        press(qapp, window, getattr(Qt.Key, f"Key_{letter.upper()}"), letter)
    assert field.property("text") == "Ab"
    assert window.backend.settings.value("game") == ""
    press(qapp, window, Qt.Key.Key_Return)
    assert window.backend.settings.value("game") == "Ab"


def test_typed_text_is_kept_when_its_page_or_the_window_goes(qapp, window: SettingsWindow) -> None:
    """A click in the side navigation unloads the page and closing hides it:
    neither may lose what was typed in a field that writes when it is left."""
    window.show_page("game")
    settle(qapp)
    (field,) = find(window, "Field", key="game")
    QMetaObject.invokeMethod(field, "forceActiveFocus")
    type_text(qapp, window, "Xy")
    (entry,) = [
        item for item in find(window, "NavItem") if variant(item.property("modelData")).get("key") == "appearance"
    ]
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, drawn(entry).center().toPoint())
    settle(qapp)
    assert window.rootObject().property("page") == "appearance"
    assert window.backend.settings.value("game") == "Xy"

    window.show_page("game")
    settle(qapp)
    (field,) = find(window, "Field", key="game")
    QMetaObject.invokeMethod(field, "forceActiveFocus")
    type_text(qapp, window, "Z")
    window.close()
    settle(qapp)
    assert window.backend.settings.value("game") == "XyZ"


def test_the_ocr_language_can_be_typed(qapp, window: SettingsWindow) -> None:
    """The list holds the common languages; rapid.py reads more (latin, th, el...)."""
    window.show_page("translation")
    settle(qapp)
    (combo,) = find(window, "Combo", key="lang")
    assert combo.property("editable")


def test_a_hotkey_field_says_why_a_key_was_not_taken(qapp, window: SettingsWindow) -> None:
    window.show_page("hotkeys")
    settle(qapp)
    (field,) = find(window, "HotkeyField", key="hotkey_toggle")
    QMetaObject.invokeMethod(field, "forceActiveFocus")
    settle(qapp)
    press(qapp, window, Qt.Key.Key_A, "a")
    assert field.property("refusal") == "add Ctrl, Alt or Win"  # a letter alone
    press(qapp, window, Qt.Key.Key_Adiaeresis, "ä", Qt.KeyboardModifier.ControlModifier)
    assert field.property("refusal") == "that key cannot be a hotkey"  # Ctrl is there; the key is the trouble
    assert window.backend.settings.value("hotkey_toggle") == "ctrl+shift+t"


def test_a_hotkey_field_refuses_a_combination_another_action_has(qapp, window: SettingsWindow) -> None:
    """Windows gives a combination to one registration: the second action would never fire."""
    window.show_page("hotkeys")
    settle(qapp)
    (field,) = find(window, "HotkeyField", key="hotkey_toggle")
    QMetaObject.invokeMethod(field, "forceActiveFocus")
    settle(qapp)
    ctrl_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    press(qapp, window, Qt.Key.Key_P, "P", ctrl_shift)  # Pause / resume has it
    assert field.property("refusal") == "used by Pause / resume" and field.property("activeFocus")
    assert window.backend.settings.value("hotkey_toggle") == "ctrl+shift+t"
    press(qapp, window, Qt.Key.Key_Y, "Y", ctrl_shift)
    assert window.backend.settings.value("hotkey_toggle") == "ctrl+shift+y"


def test_the_first_step_up_from_the_games_own_size_is_readable(qapp, window: SettingsWindow) -> None:
    window.show_page("appearance")
    settle(qapp)
    window.backend.set("subtitle_font_px", 0)
    settle(qapp)
    (stepper,) = [item for item in find(window, "Stepper", key="subtitle_font_px") if item.isVisible()]  # not Home's
    QMetaObject.invokeMethod(stepper, "forceActiveFocus")
    sizes = []
    for key in (Qt.Key.Key_Up, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Down):
        press(qapp, window, key)
        sizes.append(window.backend.settings.value("subtitle_font_px"))
    assert sizes == [36, 38, 36, 34]  # not 2 px: then two at a time, as before


def test_the_preview_shows_only_where_the_overlay_draws_subtitles(qapp, window: SettingsWindow) -> None:
    """In place, or with the whole window, the overlay draws in the game's colours: no pill to preview."""
    window.show_page("appearance")
    settle(qapp)
    (preview,) = find(window, "SubtitlePreview")
    assert preview.property("visible")
    window.backend.set("render", "inplace")
    settle(qapp)
    assert not preview.property("visible")
    window.backend.set("render", "subtitle")
    window.backend.set("roi", "")
    settle(qapp)
    assert not preview.property("visible")


def test_a_key_the_store_refuses_stays_in_its_field(qapp, window: SettingsWindow) -> None:
    class RefusingStore(MemorySecretStore):
        def set(self, name: str, value: str) -> None:
            raise OSError("vault refused")

    window.show_page("translation")
    settle(qapp)
    (entry,) = [item for item in find(window, "KeyEntry", name="DEEPL_AUTH_KEY") if item.isVisible()]  # not Home's
    (field,) = [field for field in find(window, "Field", secret=True) if field.parentItem() is entry]
    QMetaObject.invokeMethod(field, "forceActiveFocus")
    type_text(qapp, window, "abc")
    window.backend.secrets = RefusingStore()
    press(qapp, window, Qt.Key.Key_Return)  # Enter saves
    assert field.property("text") == "abc" and "vault refused" in window.backend.problem
    window.backend.secrets = MemorySecretStore()
    press(qapp, window, Qt.Key.Key_Return)
    assert field.property("text") == "" and window.backend.secrets.get("DEEPL_AUTH_KEY") == "abc"


def test_a_new_page_opens_at_its_top(qapp, window: SettingsWindow) -> None:
    window.show_page("appearance")
    settle(qapp)
    (flick,) = [obj for obj in window.objects() if obj.metaObject().className() == "QQuickFlickable"]
    flick.setProperty("contentY", 400)
    window.show_page("translation")
    settle(qapp)
    assert flick.property("contentY") == 0


def test_the_scroll_bar_shows_only_when_the_page_scrolls(qapp, window: SettingsWindow) -> None:
    window.show_page("home")
    settle(qapp)
    (bar,) = [
        bar for bar in find(window, "ThinScrollBar") if bar.parentItem().metaObject().className() == "QQuickFlickable"
    ]
    assert not bar.property("visible")
    window.show_page("appearance")
    settle(qapp)
    assert bar.property("visible")


def test_the_profile_popup_is_the_apps_own_dialog(qapp, window: SettingsWindow) -> None:
    """A Controls import without a name once made it Qt's Dialog: pinned to
    the corner, not modal, its list zero wide."""
    (popup,) = find(window, "ProfilePopup")
    QMetaObject.invokeMethod(popup, "open")
    settle(qapp)
    assert popup.property("modal") and popup.property("width") == 440
    assert popup.property("x") == (1000 - 440) / 2
    assert window.foreign_types() == []


def test_the_window_and_its_popups_follow_the_screen_scale(qapp, tmp_path: Path) -> None:
    view = open_window(qapp, tmp_path, Settings(), scale=None)  # follows the screen: 96 dpi offscreen
    try:
        assert view.ui_scale == 1.0 and view.size() == QSize(1000, 680)
        big = SimpleNamespace(logicalDotsPerInch=lambda: 144.0, availableGeometry=lambda: QRect(0, 0, 2880, 1700))
        view._on_screen_changed(big)  # moved to a 150 % screen with room for the whole window
        settle(qapp)
        assert view.ui_scale == 1.5 and view.size() == QSize(1500, 1020)
        assert view.minimumSize() == view.maximumSize() == QSize(1500, 1020)
        (popup,) = find(view, "ProfilePopup")
        assert popup.property("scale") == 1.5  # drawn above the page, so scaled itself
        (combo,) = find(view, "Combo", key="target_lang")
        combo_popup = next(p for p in view.popups() if p.parent() is combo)
        assert combo_popup.property("scale") == 1.5
        # Scaled from its corner, so the dialog's card is drawn in the middle of the window.
        QMetaObject.invokeMethod(popup, "open")
        settle(qapp)
        assert drawn(popup.property("background")).center() == QPointF(750, 510)
        QMetaObject.invokeMethod(popup, "close")
        settle(qapp)
        # A list with no room below opens right above its box, not far above it.
        view.show_page("advanced")
        settle(qapp)
        (combo,) = find(view, "Combo", key="translator")
        combo_popup = next(p for p in view.popups() if p.parent() is combo)
        QMetaObject.invokeMethod(combo_popup, "open")
        settle(qapp)
        box, shown = drawn(combo), drawn(combo_popup.property("background"))
        assert shown.bottom() < box.top() <= shown.bottom() + 2 * 1.5 + 1
        QMetaObject.invokeMethod(combo_popup, "close")
        view.show_page("appearance")
        settle(qapp)
        assert view.rootObject().property("fullHeight") > 1.4 * 1000  # the page's height, in screen pixels
    finally:
        close_window(qapp, view)
