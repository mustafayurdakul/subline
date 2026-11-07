"""The hotkey code that needs no desktop: reading combinations and handing
WM_HOTKEY to its callback. Registering real hotkeys is in test_hotkeys.py."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import pytest

from gametl.app.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, WM_HOTKEY, GlobalHotkeys, parse_combo


def test_parse_combo_letters_function_and_named_keys() -> None:
    assert parse_combo("ctrl+shift+t") == (MOD_CONTROL | MOD_SHIFT, ord("T"))
    assert parse_combo("Alt + F5") == (MOD_ALT, 0x74)
    assert parse_combo("ctrl+space") == (MOD_CONTROL, 0x20)
    assert parse_combo("f12") == (0, 0x7B)


@pytest.mark.parametrize("bad", ["", "ctrl+", "ctrl+shift", "meta+x", "ctrl+hyper", "ctrl+f99", "ctrl+ş", "alt+٣"])
def test_parse_combo_rejects_nonsense(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_combo(bad)


def deliver(hotkeys: GlobalHotkeys, message: int, hotkey_id: int) -> tuple[bool, int]:
    """Pass a Windows message to the filter the way Qt does: its address."""
    msg = wintypes.MSG(message=message, wParam=hotkey_id)
    return hotkeys.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))


def test_a_hotkey_message_runs_its_callback_and_others_pass_through() -> None:
    hotkeys = GlobalHotkeys()
    fired = []
    hotkeys._callbacks[7] = lambda: fired.append(7)
    assert deliver(hotkeys, WM_HOTKEY, 7) == (True, 0)
    assert fired == [7]
    assert deliver(hotkeys, WM_HOTKEY, 8) == (False, 0)  # an id this filter never registered
    assert deliver(hotkeys, WM_HOTKEY + 1, 7) == (False, 0)  # not a hotkey message
    assert fired == [7]
