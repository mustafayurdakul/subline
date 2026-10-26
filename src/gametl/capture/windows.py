"""Win32 helpers: DPI awareness, window enumeration, window rectangles.

Pure ctypes, no pywin32 dependency. Everything here returns physical pixels,
which is only meaningful once `enable_per_monitor_dpi_awareness()` has run in
the process (call it before any window or Qt code).
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

from .base import Rect

_user32 = ctypes.windll.user32
_dwmapi = ctypes.windll.dwmapi

# DwmGetWindowAttribute attributes
_DWMWA_CLOAKED = 14
_DWMWA_EXTENDED_FRAME_BOUNDS = 9

# SetProcessDpiAwarenessContext
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetClientRect.restype = wintypes.BOOL
_user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_user32.ClientToScreen.restype = wintypes.BOOL
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
_user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
_dwmapi.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
]
_dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long  # HRESULT


def enable_per_monitor_dpi_awareness() -> bool:
    """Make this process Per-Monitor-V2 DPI aware so all coordinates are
    physical pixels. Must run before any window is created. Returns False if
    the awareness was already set (by a manifest or an earlier call)."""
    return bool(_user32.SetProcessDpiAwarenessContext(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))


@dataclass(slots=True, frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    rect: Rect  # extended frame bounds, physical pixels

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


def window_title(hwnd: int) -> str:
    n = _user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def is_cloaked(hwnd: int) -> bool:
    """Windows 10/11 keep some 'visible' windows cloaked (suspended store apps,
    windows on other virtual desktops). They cannot be captured usefully."""
    cloaked = wintypes.DWORD(0)
    hr = _dwmapi.DwmGetWindowAttribute(hwnd, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return hr == 0 and cloaked.value != 0


def window_rect(hwnd: int) -> Rect:
    """Visible bounds of the window (excludes the invisible resize border that
    GetWindowRect includes on Windows 10+)."""
    rect = wintypes.RECT()
    hr = _dwmapi.DwmGetWindowAttribute(hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect))
    if hr != 0:
        _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def client_rect_on_screen(hwnd: int) -> Rect:
    """The client area (what a game draws into) in screen coordinates."""
    rect = wintypes.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    _user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return (
        origin.x,
        origin.y,
        origin.x + rect.right - rect.left,
        origin.y + rect.bottom - rect.top,
    )


def is_minimized(hwnd: int) -> bool:
    return bool(_user32.IsIconic(hwnd))


def is_window(hwnd: int) -> bool:
    """False once the window has been destroyed."""
    return bool(_user32.IsWindow(hwnd))


def foreground_window() -> int:
    return int(_user32.GetForegroundWindow() or 0)


def window_process_id(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def list_windows(min_size: int = 64, include_own: bool = False) -> list[WindowInfo]:
    """Top-level windows a user would recognise: visible, titled, not cloaked,
    at least `min_size` pixels in both directions. Windows of this process
    (the settings window) are left out unless `include_own`, so a typed
    title never matches the app itself."""
    found: list[WindowInfo] = []
    own_pid = os.getpid()

    @_WNDENUMPROC
    def _enum(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        title = window_title(hwnd)
        if not title:
            return True
        if not include_own and window_process_id(hwnd) == own_pid:
            return True
        if is_cloaked(hwnd):
            return True
        rect = window_rect(hwnd)
        if rect[2] - rect[0] < min_size or rect[3] - rect[1] < min_size:
            return True
        found.append(WindowInfo(int(hwnd), title, window_class(hwnd), rect))
        return True

    _user32.EnumWindows(_enum, 0)
    return found


def find_window(title_substring: str) -> WindowInfo | None:
    """First visible window whose title contains `title_substring`
    (case-insensitive). An exact title match wins over a substring match."""
    needle = title_substring.casefold()
    candidates = [w for w in list_windows() if needle in w.title.casefold()]
    if not candidates:
        return None
    return next((w for w in candidates if w.title.casefold() == needle), candidates[0])
