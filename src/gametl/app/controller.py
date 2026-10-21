"""Builds and runs the overlay from a Settings object. Shared by the command
line, the tray icon and the settings window."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..capture.windows import client_rect_on_screen, find_window, window_rect, window_title
from ..ocr.rapid import RapidOcrEngine
from ..overlay.selector import AreaSelector, rect_to_zone_spec
from ..overlay.window import OverlayWindow
from ..tracking.filters import LineFilter
from ..translate.base import Translator
from ..translate.cache import TranslationCache
from ..translate.dummy import EchoTranslator, UppercaseTranslator, VerboseTranslator
from ..translate.service import TranslationService
from .config import ProfileStore, Settings, slug
from .pipeline import PipelineConfig, PipelineThread

Box = tuple[int, int, int, int]


# -- helpers -----------------------------------------------------------------


def parse_zone(spec: str | None, width: int, height: int) -> Box | None:
    """'x,y,w,h' as fractions (all <= 1) or pixels -> (x0, y0, x1, y1)."""
    if not spec:
        return None
    try:
        x, y, w, h = (float(v) for v in spec.split(","))
    except ValueError:
        return None
    if max(x, y, w, h) <= 1.0:
        x, y, w, h = x * width, y * height, w * width, h * height
    return max(0, int(x)), max(0, int(y)), min(width, int(x + w)), min(height, int(y + h))


def client_area_in_frame(hwnd: int) -> tuple[Box, Box | None]:
    """(frame box, client area within the frame or None when degenerate)."""
    rect = window_rect(hwnd)
    frame_w, frame_h = rect[2] - rect[0], rect[3] - rect[1]
    c = client_rect_on_screen(hwnd)
    area: Box | None = (
        max(0, c[0] - rect[0]),
        max(0, c[1] - rect[1]),
        min(frame_w, c[2] - rect[0]),
        min(frame_h, c[3] - rect[1]),
    )
    if area[2] <= area[0] or area[3] <= area[1]:
        area = None
    return (0, 0, frame_w, frame_h), area


def load_user_env(name: str) -> str | None:
    """The variable from this process, else from the Windows user environment
    (set after the process started), copied into os.environ."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    if value:
        os.environ[name] = str(value)
        return str(value)
    return None


def ensure_anthropic_credentials() -> bool:
    """True when the SDK will find credentials."""
    if load_user_env("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


def grab_screen_region(rect: Box, path: str) -> None:
    """Screenshot of a screen rectangle including layered windows (ours)."""
    from PIL import ImageGrab

    image = ImageGrab.grab(bbox=rect, include_layered_windows=True, all_screens=True)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    image.save(path)


def build_offline_translator(settings: Settings, store: ProfileStore) -> Translator:
    from ..translate.offline import OfflineTranslator

    return OfflineTranslator.from_models_dir(store.models_dir, settings.effective_source_lang, settings.target_lang)


def build_deepl_translator() -> Translator:
    from ..translate.deepl import DeepLTranslator

    return DeepLTranslator(auth_key=load_user_env("DEEPL_AUTH_KEY"))


def build_draft_translator(settings: Settings, store: ProfileStore) -> Translator | None:
    if not settings.draft or settings.draft == settings.translator:
        return None
    if settings.draft == "offline":
        return build_offline_translator(settings, store)
    if settings.draft == "deepl":
        return build_deepl_translator()
    return None


def build_translator(settings: Settings, game: str, store: ProfileStore | None = None) -> Translator:
    if settings.translator == "uppercase":
        return UppercaseTranslator()
    if settings.translator == "verbose":
        return VerboseTranslator()
    if settings.translator == "echo":
        return EchoTranslator()
    if settings.translator == "offline":
        return build_offline_translator(settings, store or ProfileStore())
    if settings.translator == "deepl":
        return build_deepl_translator()
    from ..translate.claude import ClaudeTranslator

    glossary = None
    if settings.glossary_path:
        with open(settings.glossary_path, encoding="utf-8") as fh:
            glossary = json.load(fh)
    return ClaudeTranslator(
        model=settings.model,
        effort=settings.effort,
        thinking=settings.thinking,
        structured=settings.structured,
        game=game,
        glossary=glossary,
        style=settings.tone or None,
        source_lang=settings.effective_source_lang,
        target_lang=settings.target_lang,
    )


class OverlayController(QObject):
    """Owns the OCR engine, translation service, overlay window and pipeline
    thread for one running session; start() tears down any previous one."""

    status = Signal(str)
    running_changed = Signal(bool)
    paused_changed = Signal(bool)
    area_selected = Signal(str)  # zone spec 'x,y,w,h' as fractions of the client area

    def __init__(self, store: ProfileStore | None = None, parent=None) -> None:
        super().__init__(parent)
        self.store = store or ProfileStore()
        self.settings: Settings | None = None
        self.hwnd: int | None = None
        self.title = ""
        self.overlay: OverlayWindow | None = None
        self.worker: PipelineThread | None = None
        self.service: TranslationService | None = None
        self.translator: Translator | None = None
        self.cache: TranslationCache | None = None
        self.cache_path: Path | None = None
        self._engines: dict[str, RapidOcrEngine] = {}
        self._selector: AreaSelector | None = None

    # -- state -------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self.worker is not None

    @property
    def paused(self) -> bool:
        return bool(self.worker and self.worker.paused)

    def _say(self, text: str) -> None:
        self.status.emit(text)

    # -- lifecycle ---------------------------------------------------------

    def resolve_window(self, settings: Settings, hwnd: int | None = None, wait: float = 0.0) -> tuple[int, str] | None:
        if hwnd:
            return hwnd, window_title(hwnd)
        if not settings.window_match:
            return None
        deadline = time.perf_counter() + wait
        info = find_window(settings.window_match)
        while info is None and time.perf_counter() < deadline:
            time.sleep(0.5)
            info = find_window(settings.window_match)
        return (info.hwnd, info.title) if info else None

    def engine(self, lang: str, frame_w: int = 1280, frame_h: int = 720) -> RapidOcrEngine:
        engine = self._engines.get(lang)
        if engine is None:
            self._say(f"loading OCR model ({lang})... first use downloads it")
            engine = RapidOcrEngine(lang=lang, model_root_dir=str(self.store.models_dir / "ocr"))
            engine.warm_up(frame_w, frame_h)
            self._engines[lang] = engine
        return engine

    def start(self, settings: Settings, hwnd: int | None = None, wait: float = 0.0) -> bool:
        if self.running:
            self.stop()
        resolved = self.resolve_window(settings, hwnd, wait)
        if resolved is None:
            self._say(f"no visible window matching {settings.window_match!r}")
            return False
        self.hwnd, self.title = resolved
        self.settings = settings.copy()
        game = settings.game or self.title or "game"

        if settings.translator == "claude" and not ensure_anthropic_credentials():
            self._say("no Anthropic credentials: set ANTHROPIC_API_KEY in your user environment variables")
            return False
        try:
            self.translator = build_translator(settings, game, self.store)
            if settings.draft == "offline" and settings.translator != "offline":
                self._say("loading offline draft model...")
            draft = build_draft_translator(settings, self.store)
        except (OSError, ValueError, RuntimeError) as exc:
            self._say(f"translator setup failed: {exc}")
            return False

        frame, area = client_area_in_frame(self.hwnd)
        if settings.include_frame:
            area = None
        ax0, ay0, ax1, ay1 = area or frame
        roi = parse_zone(settings.roi, ax1 - ax0, ay1 - ay0)
        if roi is not None:
            roi = (roi[0] + ax0, roi[1] + ay0, roi[2] + ax0, roi[3] + ay0)
        zones: list[Box] = []
        for spec in settings.ignore_zones:
            z = parse_zone(spec, ax1 - ax0, ay1 - ay0)
            if z is not None:
                zones.append((z[0] + ax0, z[1] + ay0, z[2] + ax0, z[3] + ay0))
        patterns = [p for p in settings.ignore_patterns if p.strip()]
        line_filter = LineFilter.compile(zones, patterns) if (zones or patterns) else None

        self.cache_path = None
        if settings.use_cache_file:
            self.cache_path = self.store.cache_dir / f"{slug(game)}.{settings.target_lang}.{self.translator.name}.json"
        self.cache = TranslationCache(self.cache_path)
        self.service = TranslationService(
            self.translator,
            self.cache,
            target_lang=settings.target_lang,
            source_lang=settings.effective_source_lang,
            on_status=self._say,
            draft_translator=draft,
        )

        engine = self.engine(settings.lang, frame[2], frame[3])

        self.overlay = OverlayWindow(
            self.hwnd,
            hide_when_unfocused=settings.hide_when_unfocused,
            exclude_from_capture=settings.exclude_from_capture,
            font_family=settings.font,
        )
        config = PipelineConfig(
            area=area,
            roi=roi,
            fps=settings.fps,
            full_scan_every=settings.full_scan_every,
            stable_frames=settings.stable_frames,
            max_missing=settings.max_missing,
            style=settings.style,
            line_filter=line_filter,
            debug=settings.debug,
            dump_dir=settings.dump_dir or None,
        )
        self.worker = PipelineThread(self.hwnd, engine, self.service, config)
        self.worker.blocks_ready.connect(self.overlay.set_blocks)
        self.worker.status.connect(self._say)
        self.overlay.target_lost.connect(self._on_target_lost)

        self.overlay.start()
        self.worker.start()
        self.running_changed.emit(True)
        self._say(f"running on {self.title!r}: {settings.effective_source_lang} -> {settings.target_lang} via {self.translator.name}")
        return True

    def _on_target_lost(self) -> None:
        self._say("game window closed")
        self.stop()

    def stop(self) -> None:
        worker, overlay, service = self.worker, self.overlay, self.service
        self.worker = None
        if worker is not None:
            worker.stop()
            worker.wait(3000)
        if overlay is not None:
            overlay.close()
            overlay.deleteLater()
            self.overlay = None
        if service is not None:
            service.shutdown()
            self.service = None
        self.running_changed.emit(False)
        self.paused_changed.emit(False)
        self._say("stopped")

    def toggle(self, settings: Settings) -> None:
        if self.running:
            self.stop()
        else:
            self.start(settings)

    def set_paused(self, paused: bool) -> None:
        if self.worker is None:
            return
        self.worker.paused = paused
        self.paused_changed.emit(paused)
        self._say("paused" if paused else "resumed")

    def rescan(self) -> None:
        if self.worker is not None:
            self.worker.rescan()
            self._say("rescanning")

    # -- area selection ------------------------------------------------------

    def select_area(self, settings: Settings | None = None) -> bool:
        """Open the drag-to-select layer over the game window. The result
        becomes the only area read and translated; a running overlay
        restarts on it. Uses the running window, else the one `settings`
        names."""
        if self._selector is not None:
            return True
        hwnd = self.hwnd
        if hwnd is None or not self.running:
            resolved = self.resolve_window(settings or self.settings or Settings())
            if resolved is None:
                self._say("select area: no game window found; start the game or set its title first")
                return False
            hwnd = resolved[0]
        self._area_hwnd = hwnd
        self._selector = AreaSelector(window_rect(hwnd))
        self._selector.selected.connect(self._apply_selected_area)
        self._selector.cancelled.connect(self._selection_cancelled)
        self._selector.start()
        self._say("drag to select the area to translate (Esc cancels)")
        return True

    def _selection_cancelled(self) -> None:
        self._selector = None
        self._say("area selection cancelled")

    def _apply_selected_area(self, rect: tuple) -> None:
        self._selector = None
        hwnd = getattr(self, "_area_hwnd", None) or self.hwnd
        frame, area = client_area_in_frame(hwnd)
        if self.settings is not None and self.settings.include_frame:
            area = None
        spec = rect_to_zone_spec(tuple(rect), area or frame)
        self._say(f"area selected: {spec}; translating only that area")
        if self.settings is not None:
            self.settings.roi = spec
            self.settings.full_scan_every = 0
        self.area_selected.emit(spec)
        if self.running and self.settings is not None:
            self.start(self.settings, hwnd)

    def clear_area(self) -> None:
        if self.settings is not None:
            self.settings.roi = ""
        self.area_selected.emit("")
        self._say("area cleared: translating the whole window")
        if self.running and self.settings is not None:
            self.start(self.settings, self.hwnd)

    # -- reporting ---------------------------------------------------------

    def stats_text(self) -> str:
        parts = []
        if self.worker and self.worker.ocr_ms:
            s = sorted(self.worker.ocr_ms)
            parts.append(f"frames {self.worker.frames}, ocr median {s[len(s) // 2]:.0f}ms max {s[-1]:.0f}ms")
        if self.service:
            st = self.service.stats
            parts.append(
                f"translation: {st['requests']} requests, {st['items']} items sent, {st['translated']} translated, "
                f"{st['cache_hits']} cache hits, {st['errors']} errors"
                + (f"; cache {len(self.cache)} entries" if self.cache is not None else "")
            )
            if self.service.latencies_ms:
                lat = sorted(self.service.latencies_ms)
                parts.append(f"request latency: median {lat[len(lat) // 2]:.0f}ms min {lat[0]:.0f}ms max {lat[-1]:.0f}ms")
            if self.service.draft_latencies_ms:
                lat = sorted(self.service.draft_latencies_ms)
                parts.append(
                    f"draft: {st['drafts']} items, latency median {lat[len(lat) // 2]:.0f}ms max {lat[-1]:.0f}ms"
                )
        totals = getattr(self.translator, "usage_totals", None)
        calls = getattr(self.translator, "calls", 0)
        if totals and calls and self.settings:
            from ..translate.claude import estimate_cost_usd

            cost = estimate_cost_usd(self.settings.model, totals)
            cost_text = f" ~${cost:.5f}" if cost is not None else ""
            parts.append(
                f"tokens: {totals['input']} in, {totals['output']} out, {totals['cache_read']} cache read, "
                f"{totals['cache_write']} cache write over {calls} calls{cost_text}"
            )
        return "\n".join(parts)
