"""Global hotkeys through Win32 RegisterHotKey, delivered to callbacks via a
Qt native event filter (WM_HOTKEY arrives on the thread's message queue)."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

_user32 = ctypes.windll.user32
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312

# fmt: off
_MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED_KEYS = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "pause": 0x13, "scrolllock": 0x91, "printscreen": 0x2C,
}
# fmt: on


def parse_combo(combo: str) -> tuple[int, int]:
    """'ctrl+shift+t' -> (modifier flags, virtual-key code). Raises ValueError."""
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    mods = 0
    for part in parts[:-1]:
        if part not in _MODIFIERS:
            raise ValueError(f"unknown modifier {part!r} in {combo!r}")
        mods |= _MODIFIERS[part]
    key = parts[-1]
    if key in _MODIFIERS:
        raise ValueError(f"{combo!r} has no key, only modifiers")
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return mods, ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return mods, 0x70 + int(key[1:]) - 1
    if key in _NAMED_KEYS:
        return mods, _NAMED_KEYS[key]
    raise ValueError(f"unknown key {key!r} in {combo!r}")


class GlobalHotkeys(QAbstractNativeEventFilter):
    """Install with `app.installNativeEventFilter(hotkeys)` before registering."""

    def __init__(self) -> None:
        super().__init__()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._names: dict[str, int] = {}
        self._next_id = 1

    def register(self, name: str, combo: str, callback: Callable[[], None]) -> bool:
        """Register (or re-register) `name` as `combo`. False when the combo
        is invalid or already taken by another program."""
        self.unregister(name)
        try:
            mods, vk = parse_combo(combo)
        except ValueError:
            return False
        hotkey_id = self._next_id
        if not _user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, vk):
            return False
        self._next_id += 1
        self._callbacks[hotkey_id] = callback
        self._names[name] = hotkey_id
        return True

    def unregister(self, name: str) -> None:
        hotkey_id = self._names.pop(name, None)
        if hotkey_id is not None:
            _user32.UnregisterHotKey(None, hotkey_id)
            self._callbacks.pop(hotkey_id, None)

    def unregister_all(self) -> None:
        for name in list(self._names):
            self.unregister(name)

    @property
    def registered(self) -> list[str]:
        return list(self._names)

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                callback = self._callbacks.get(int(msg.wParam))
                if callback is not None:
                    callback()
                    return True, 0
        return False, 0
