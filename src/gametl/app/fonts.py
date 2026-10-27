"""The fonts the app brings along (src/gametl/fonts, OFL-licensed), so the
subtitles look the same on every computer: registered with Qt once per
process, listed first in the settings window's font choice."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

BUNDLED_FAMILIES = ("Source Sans 3", "Fira Sans", "Barlow Semi Condensed")  # in the order offered
_loaded = False


def fonts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fonts"


def load_bundled_fonts() -> None:
    """Register every bundled font file with Qt (needs a QGuiApplication)."""
    global _loaded
    if _loaded:
        return
    for path in sorted(fonts_dir().glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))
    _loaded = True
