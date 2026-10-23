"""Builds and runs the overlay from a Settings object. Shared by the command
line, the tray icon and the settings window."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
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
from .credentials import (
    DEEPL_KEY,
    SecretStore,
    WindowsCredentialStore,
    anthropic_api_key,
    has_anthropic_credentials,
    resolve_key,
)
from .pipeline import PipelineConfig, PipelineThread

Box = tuple[int, int, int, int]
RGB = tuple[int, int, int]


# -- zones and colours -------------------------------------------------------------


def parse_zone(spec: str | None, width: int, height: int) -> Box | None:
    """'x,y,w,h' as fractions (all <= 1) or pixels -> (x0, y0, x1, y1), clamped."""
    if not spec:
        return None
    try:
        x, y, w, h = (float(v) for v in spec.split(","))
    except ValueError:
        return None
    if max(x, y, w, h) <= 1.0:
        x, y, w, h = x * width, y * height, w * width, h * height
    return max(0, int(x)), max(0, int(y)), min(width, int(x + w)), min(height, int(y + h))


def offset_zone(zone: Box, dx: int, dy: int) -> Box:
    return zone[0] + dx, zone[1] + dy, zone[2] + dx, zone[3] + dy


def parse_color(text: str, default: RGB = (255, 255, 255)) -> RGB:
    """'#RRGGBB' or 'r,g,b' -> RGB tuple; anything else gives the default."""
    text = (text or "").strip()
    try:
        if text.startswith("#") and len(text) == 7:
            return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
        if "," in text:
            r, g, b = (int(v) for v in text.split(","))
            return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
    except ValueError:
        pass
    return default


def client_area_in_frame(hwnd: int) -> tuple[Box, Box | None]:
    """(frame box, client area within the frame, or None when degenerate)."""
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


def capture_area(hwnd: int, include_frame: bool) -> tuple[Box, Box | None]:
    """(frame box, the client area within it, or None when the whole frame
    is read because `include_frame` is set or the client area is unknown)."""
    frame, client = client_area_in_frame(hwnd)
    return frame, (None if include_frame else client)


# -- screenshots ---------------------------------------------------------------------


def grab_screen_region(rect: Box, path: str) -> None:
    """Screenshot of a screen rectangle, layered windows (ours) included."""
    from PIL import ImageGrab

    image = ImageGrab.grab(bbox=rect, include_layered_windows=True, all_screens=True)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    image.save(path)


# -- translators ---------------------------------------------------------------------


def build_offline_translator(settings: Settings, store: ProfileStore) -> Translator:
    from ..translate.offline import OfflineTranslator

    return OfflineTranslator.from_models_dir(store.models_dir, settings.effective_source_lang, settings.target_lang)


def build_deepl_translator(secrets: SecretStore) -> Translator:
    from ..translate.deepl import DeepLTranslator

    found = resolve_key(DEEPL_KEY, secrets)
    return DeepLTranslator(auth_key=found[0] if found else None)


def build_draft_translator(settings: Settings, store: ProfileStore, secrets: SecretStore) -> Translator | None:
    if not settings.draft or settings.draft == settings.translator:
        return None
    if settings.draft == "offline":
        return build_offline_translator(settings, store)
    if settings.draft == "deepl":
        return build_deepl_translator(secrets)
    return None


def build_translator(settings: Settings, game: str, store: ProfileStore, secrets: SecretStore) -> Translator:
    if settings.translator == "uppercase":
        return UppercaseTranslator()
    if settings.translator == "verbose":
        return VerboseTranslator()
    if settings.translator == "echo":
        return EchoTranslator()
    if settings.translator == "offline":
        return build_offline_translator(settings, store)
    if settings.translator == "deepl":
        return build_deepl_translator(secrets)
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
        tone=settings.tone or None,
        source_lang=settings.effective_source_lang,
        target_lang=settings.target_lang,
        api_key=anthropic_api_key(secrets),
    )


def _spread(values: Iterable[float]) -> str:
    ordered = sorted(values)
    return f"median {ordered[len(ordered) // 2]:.0f}ms min {ordered[0]:.0f}ms max {ordered[-1]:.0f}ms"


class OverlayController(QObject):
    """Owns the OCR engine, translation service, overlay window and pipeline
    thread for one running session; start() tears down any previous one."""

    status = Signal(str)
    running_changed = Signal(bool)
    paused_changed = Signal(bool)
    area_selected = Signal(str)  # zone spec 'x,y,w,h' as fractions of the client area

    def __init__(self, store: ProfileStore | None = None, secrets: SecretStore | None = None, parent=None) -> None:
        super().__init__(parent)
        self.store = store or ProfileStore()
        self.secrets: SecretStore = secrets if secrets is not None else WindowsCredentialStore()
        self.settings: Settings | None = None
        self.hwnd: int | None = None
        self.title = ""
        self.overlay: OverlayWindow | None = None
        self.worker: PipelineThread | None = None
        self.service: TranslationService | None = None
        self.translator: Translator | None = None
        self.cache: TranslationCache | None = None
        self.cache_path: Path | None = None
        self._engines: dict[tuple[str, bool], RapidOcrEngine] = {}  # by (language, gpu)
        self._selector: AreaSelector | None = None
        self._selection_hwnd: int | None = None

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

    def engine(self, lang: str, gpu: bool, frame_w: int = 1280, frame_h: int = 720) -> RapidOcrEngine:
        """One warmed-up OCR engine per language and device, kept for the
        life of the controller (loading takes a second or two)."""
        engine = self._engines.get((lang, gpu))
        if engine is None:
            device = "GPU" if gpu else "CPU"
            self._say(f"loading OCR model ({lang}, {device})... first use downloads it")
            engine = RapidOcrEngine(lang=lang, use_dml=gpu, model_root_dir=str(self.store.models_dir / "ocr"))
            engine.warm_up(frame_w, frame_h)
            self._engines[(lang, gpu)] = engine
        return engine

    def start(self, settings: Settings, hwnd: int | None = None, wait: float = 0.0) -> bool:
        # 1. The window.
        if self.running:
            self.stop()
        resolved = self.resolve_window(settings, hwnd, wait)
        if resolved is None:
            self._say(f"no visible window matching {settings.window_match!r}")
            return False
        self.hwnd, self.title = resolved
        self.settings = settings.copy()
        game = settings.game or self.title or "game"

        # 2. The translators: the main one and the optional draft.
        if settings.translator == "claude" and not has_anthropic_credentials(self.secrets):
            self._say("no Anthropic key: enter one in Settings > Translation")
            return False
        try:
            self.translator = build_translator(settings, game, self.store, self.secrets)
            draft = build_draft_translator(settings, self.store, self.secrets)
        except (OSError, ValueError, RuntimeError) as exc:
            self._say(f"translator setup failed: {exc}")
            return False
        for translator in (self.translator, draft):
            if getattr(translator, "kind", None):
                self._say(f"offline model: {translator.kind} ({translator.model_dir})")  # type: ignore[union-attr]

        # 3. The translation service, the OCR engine, the overlay window and the
        #    pipeline thread that connects them.
        frame, client = capture_area(self.hwnd, settings.include_frame)
        self.service = self._build_service(settings, game, draft)
        engine = self.engine(settings.lang, settings.ocr_gpu, frame[2], frame[3])
        self.overlay = OverlayWindow(
            self.hwnd,
            hide_when_unfocused=settings.hide_when_unfocused,
            exclude_from_capture=settings.exclude_from_capture,
            font_family=settings.font,
        )
        self.worker = PipelineThread(self.hwnd, engine, self.service, self._pipeline_config(settings, frame, client))
        self.worker.blocks_ready.connect(self.overlay.set_blocks)
        self.worker.status.connect(self._say)
        self.overlay.target_lost.connect(self._on_target_lost)

        # 4. Go.
        self.overlay.start()
        self.worker.start()
        self.running_changed.emit(True)
        self._say(
            f"running on {self.title!r}: {settings.effective_source_lang} -> {settings.target_lang} "
            f"via {self.translator.name}"
        )
        return True

    def _build_service(self, settings: Settings, game: str, draft: Translator | None) -> TranslationService:
        assert self.translator is not None
        self.cache_path = None
        if settings.use_cache_file:
            self.cache_path = self.store.cache_dir / f"{slug(game)}.{settings.target_lang}.{self.translator.name}.json"
        self.cache = TranslationCache(self.cache_path)
        return TranslationService(
            self.translator,
            self.cache,
            target_lang=settings.target_lang,
            source_lang=settings.effective_source_lang,
            on_status=self._say,
            draft_translator=draft,
        )

    @staticmethod
    def _pipeline_config(settings: Settings, frame: Box, client: Box | None) -> PipelineConfig:
        """Zones in the settings are fractions of the read area (the client
        area, or the whole frame); the pipeline wants frame pixels."""
        ax0, ay0, ax1, ay1 = client or frame
        width, height = ax1 - ax0, ay1 - ay0
        roi = parse_zone(settings.roi, width, height)
        zones = (parse_zone(spec, width, height) for spec in settings.ignore_zones)
        ignore_zones = [offset_zone(zone, ax0, ay0) for zone in zones if zone is not None]
        patterns = [p for p in settings.ignore_patterns if p.strip()]
        return PipelineConfig(
            area=client,
            roi=offset_zone(roi, ax0, ay0) if roi is not None else None,
            fps=settings.fps,
            full_scan_every=settings.full_scan_every,
            stable_frames=settings.stable_frames,
            max_missing=settings.max_missing,
            style=settings.style,
            line_filter=LineFilter.compile(ignore_zones, patterns) if (ignore_zones or patterns) else None,
            render=settings.render,
            subtitle_font_px=settings.subtitle_font_px,
            subtitle_color=parse_color(settings.subtitle_color),
            subtitle_pill=settings.subtitle_background == "pill",
            subtitle_position=settings.subtitle_position,
            subtitle_hide_source=settings.subtitle_hide_source,
            debug=settings.debug,
            dump_dir=settings.dump_dir or None,
        )

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
        active = settings or self.settings or Settings()
        hwnd = self.hwnd
        if hwnd is None or not self.running:
            resolved = self.resolve_window(active)
            if resolved is None:
                self._say("select area: no game window found; start the game or set its title first")
                return False
            hwnd = resolved[0]
        self._selection_hwnd = hwnd
        frame, client = capture_area(hwnd, active.include_frame)
        ax0, _, ax1, _ = client or frame
        self._selector = AreaSelector(window_rect(hwnd), mirror_x=active.center_zone, center_x=(ax0 + ax1) // 2)
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
        hwnd = self._selection_hwnd or self.hwnd
        assert hwnd is not None
        include_frame = self.settings is not None and self.settings.include_frame
        frame, client = capture_area(hwnd, include_frame)
        spec = rect_to_zone_spec(tuple(rect), client or frame)
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
            parts.append(f"frames {self.worker.frames}, ocr {_spread(self.worker.ocr_ms)}")
        if self.service:
            st = self.service.stats
            cache_note = f"; cache {len(self.cache)} entries" if self.cache is not None else ""
            parts.append(
                f"translation: {st['requests']} requests, {st['items']} items sent, {st['translated']} translated, "
                f"{st['cache_hits']} cache hits, {st['errors']} errors{cache_note}"
            )
            if self.service.latencies_ms:
                parts.append(f"request latency: {_spread(self.service.latencies_ms)}")
            if self.service.draft_latencies_ms:
                parts.append(f"draft: {st['drafts']} items, latency {_spread(self.service.draft_latencies_ms)}")
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
