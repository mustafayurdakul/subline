"""Settings and per-game profiles.

Everything the pipeline, translator and overlay can be told lives in one
`Settings` dataclass. Profiles are Settings saved as JSON under
%APPDATA%\\gametl\\profiles\\<name>.json; config.json next to them remembers
the last profile used. A profile matches a game by `window_match`, a
case-insensitive substring of the window title.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOTKEYS: dict[str, str] = {
    "toggle": "ctrl+shift+t",  # start / stop the overlay
    "pause": "ctrl+shift+p",  # hide translations, keep running
    "rescan": "ctrl+shift+r",  # forget tracked blocks and read the screen afresh
    "select": "ctrl+shift+a",  # drag-select the area to translate (e.g. the subtitle strip)
    "settings": "ctrl+shift+s",  # open the settings window
}

# OCR sometimes reads a number or a symbol out of background detail; a line
# with no letter in any script is never a subtitle. \W matches non-word
# characters, \d digits, _ the one word character that is not a letter.
NO_LETTERS_PATTERN = r"^[\W\d_]*$"

BOTTOM_STRIP = "0,0.75,1,0.25"  # the area most games' subtitles fall in: the bottom quarter


@dataclass
class Settings:
    # target
    window_match: str = ""  # substring of the game window title
    game: str = ""  # name for the prompt and the cache; default: window title
    include_frame: bool = False  # read the title bar / frame too
    # The only area read and translated: x,y,w,h (fractions or px of the client area); empty = the whole area.
    roi: str = BOTTOM_STRIP
    center_zone: bool = (
        False  # keep a selected area symmetric about the client area's centre (Shift inverts while dragging)
    )
    # subtitle mode: with an area set, render translations in it with one fixed style
    render: str = "subtitle"  # "subtitle" | "inplace" (per-block, at the OCR box)
    subtitle_font_px: int = 0  # 0 = the game's own subtitle size, learned from the first lines and then held
    subtitle_color: str = ""  # "#RRGGBB"; empty = the game's own subtitle colour, sampled from the frame
    subtitle_background: str = "pill"  # "pill" | "shadow" (soft drop shadow, no box) | "none" (outlined text)
    subtitle_pill_alpha: int = 230  # opacity of the pill, 0..255
    subtitle_bold: bool = False
    subtitle_position: str = "bottom"  # "bottom" of the area (steady) | "source" (where the game drew it) | "center"
    subtitle_hide_source: bool = False  # cover the original line when the subtitle is drawn elsewhere
    # HUD text sharing the area: subtitles are centred and one size; prompts and objectives are not.
    subtitle_center_tolerance: int = 10  # % of the area width a block's centre may be off the area's centre; 0 = off
    subtitle_size_tolerance: int = 35  # % a block's line height may differ from the learned subtitle size; 0 = off
    # languages and OCR
    lang: str = "en"  # OCR model language
    ocr_gpu: bool = False  # run OCR on the GPU through DirectML (any DirectX 12 card)
    source_lang: str = "en"  # what the translator is told the text is in; empty = same as lang
    target_lang: str = "tr"
    # translation
    translator: str = "deepl"  # deepl | claude | offline | uppercase | echo | verbose
    draft: str = ""  # "" | "offline" | "deepl": fast draft shown until the translator answers
    model: str = "claude-haiku-5-5"
    effort: str = "low"
    thinking: str = "disabled"
    structured: bool = False
    glossary_path: str = ""
    tone: str = ""
    use_cache_file: bool = True
    # appearance and ignores
    style: str = "auto"
    font: str = "Segoe UI"
    ignore_zones: list[str] = field(default_factory=list)
    ignore_patterns: list[str] = field(default_factory=lambda: [NO_LETTERS_PATTERN])
    short_line_confidence: float = 0.9  # a line of one or two letters needs this OCR confidence; 0 = off
    # pipeline
    fps: float = 10.0
    full_scan_every: int = 0  # with a zone: also sweep the rest of the area every N frames (0 = never)
    stable_frames: int = 1
    max_missing: int = 3
    # OCR waits while nothing in the read area changes this much: the strongest
    # local change in a small grey thumbnail, 0..255; 0 = read every frame.
    change_threshold: float = 20.0
    autosave_seconds: float = 10.0  # how soon new translations reach the cache file
    hide_when_unfocused: bool = True
    exclude_from_capture: bool = False  # hide the overlay from screen recordings, streams and screenshots
    # app
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    # debugging (command line only)
    debug: bool = False  # outline every tracked block, print per-frame stats
    dump_dir: str = ""  # save every captured frame with OCR lines and blocks drawn

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        known = {f.name for f in dataclasses.fields(cls)}
        kwargs = {k: v for k, v in (data or {}).items() if k in known}
        settings = cls(**kwargs)
        settings.hotkeys = {**DEFAULT_HOTKEYS, **(settings.hotkeys or {})}
        settings.ignore_zones = list(settings.ignore_zones or [])
        settings.ignore_patterns = list(settings.ignore_patterns or [])
        return settings

    def copy(self) -> Settings:
        return Settings.from_dict(self.to_dict())

    def set_area(self, spec: str) -> None:
        """Make `spec` the area to translate ('' for the whole window). A
        chosen area is the whole point of reading, so the periodic sweep of
        the rest is switched off with it."""
        self.roi = spec
        if spec:
            self.full_scan_every = 0

    @property
    def effective_source_lang(self) -> str:
        return self.source_lang or self.lang


def slug(text: str) -> str:
    """File-name form of a game or profile name: lower case, letters and
    digits of any script kept (a Japanese or Turkish title stays
    distinguishable), everything else collapsed to one dash."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"[^\w]+|_+", "-", text).strip("-") or "game"


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "gametl"


class ProfileStore:
    """Profiles and config on disk. `root` defaults to %APPDATA%\\gametl."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else app_dir()

    @property
    def profiles_dir(self) -> Path:
        return self.root / "profiles"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    def cache_path(self, game: str, target_lang: str, translator: str) -> Path:
        """The translation cache file for one game, language and translator."""
        return self.cache_dir / f"{slug(game)}.{target_lang}.{translator}.json"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def runtime_dir(self) -> Path:
        """The offline translator's libraries, downloaded on demand."""
        return self.root / "runtime"

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    # -- profiles ----------------------------------------------------------

    def path(self, name: str) -> Path:
        return self.profiles_dir / f"{slug(name)}.json"

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.profiles_dir.glob("*.json"))  # a missing folder yields nothing

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def load(self, name: str) -> Settings:
        with open(self.path(name), encoding="utf-8") as fh:
            return Settings.from_dict(json.load(fh))

    def save(self, name: str, settings: Settings) -> Path:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(settings.to_dict(), fh, ensure_ascii=False, indent=2)
        return path

    def delete(self, name: str) -> None:
        path = self.path(name)
        if path.exists():
            path.unlink()

    def match_window(self, title: str) -> str | None:
        """Name of the first profile whose window_match is in `title`."""
        needle_title = (title or "").casefold()
        for name in self.list():
            try:
                match = self.load(name).window_match.casefold()
            except (OSError, ValueError):
                continue
            if match and match in needle_title:
                return name
        return None

    # -- config ------------------------------------------------------------

    def load_config(self) -> dict:
        try:
            with open(self.config_path, encoding="utf-8") as fh:
                return json.load(fh) or {}
        except (OSError, ValueError):
            return {}

    def save_config(self, config: dict) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, ensure_ascii=False, indent=2)

    @property
    def last_profile(self) -> str | None:
        return self.load_config().get("last_profile") or None

    @last_profile.setter
    def last_profile(self, name: str | None) -> None:
        config = self.load_config()
        config["last_profile"] = name
        self.save_config(config)
