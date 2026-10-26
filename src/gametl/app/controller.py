"""Builds and runs the overlay from a Settings object. Shared by the command
line, the tray icon and the settings window."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal

from ..capture.windows import client_rect_on_screen, find_window, window_rect, window_title
from ..geometry import RGB, Box
from ..ocr.rapid import RapidOcrEngine
from ..overlay.selector import AreaSelector, rect_to_zone_spec
from ..overlay.window import OverlayWindow
from ..tracking.filters import LineFilter
from ..translate.base import Translator
from ..translate.cache import TranslationCache
from ..translate.dummy import EchoTranslator, UppercaseTranslator, VerboseTranslator
from ..translate.service import TranslationService
from .config import ProfileStore, Settings
from .credentials import (
    DEEPL_KEY,
    SecretStore,
    WindowsCredentialStore,
    anthropic_api_key,
    has_anthropic_credentials,
    resolve_key,
)
from .license import license_status
from .pipeline import PipelineConfig, PipelineThread

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
    # Rounded, not truncated: fractions saved with four decimals land a hair
    # under the pixel they came from, and truncation would lose that pixel.
    return max(0, round(x)), max(0, round(y)), min(width, round(x + w)), min(height, round(y + h))


def offset_zone(zone: Box, dx: int, dy: int) -> Box:
    return zone[0] + dx, zone[1] + dy, zone[2] + dx, zone[3] + dy


def parse_color(text: str) -> RGB:
    """'#RRGGBB' or 'r,g,b' -> RGB tuple; anything else gives white."""
    text = (text or "").strip()
    try:
        if text.startswith("#") and len(text) == 7:
            return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
        if "," in text:
            r, g, b = (int(v) for v in text.split(","))
            return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
    except ValueError:
        pass
    return 255, 255, 255


def capture_area(hwnd: int, include_frame: bool) -> tuple[Box, Box | None]:
    """(frame box, the client area within it, or None when the whole frame
    is read because `include_frame` is set or the client area is unknown)."""
    rect = window_rect(hwnd)
    frame = (0, 0, rect[2] - rect[0], rect[3] - rect[1])
    if include_frame:
        return frame, None
    c = client_rect_on_screen(hwnd)
    client = (
        max(0, c[0] - rect[0]),
        max(0, c[1] - rect[1]),
        min(frame[2], c[2] - rect[0]),
        min(frame[3], c[3] - rect[1]),
    )
    if client[2] <= client[0] or client[3] <= client[1]:
        return frame, None
    return frame, client


def pipeline_config(settings: Settings, frame: Box, client: Box | None) -> PipelineConfig:
    """The pipeline's view of the settings. Zones in the settings are
    fractions of the read area (the client area, or the whole frame); the
    pipeline wants frame pixels."""
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
        diff_threshold=settings.diff_threshold,
        style=settings.style,
        line_filter=LineFilter.compile(ignore_zones, patterns, short_confidence=settings.short_line_confidence),
        render=settings.render,
        subtitle_font_px=settings.subtitle_font_px,
        subtitle_color=parse_color(settings.subtitle_color) if settings.subtitle_color.strip() else None,
        subtitle_background=settings.subtitle_background,
        subtitle_pill_alpha=max(0, min(255, int(settings.subtitle_pill_alpha))),
        subtitle_bold=settings.subtitle_bold,
        subtitle_position=settings.subtitle_position,
        subtitle_hide_source=settings.subtitle_hide_source,
        subtitle_center_tolerance=max(0, settings.subtitle_center_tolerance) / 100,
        subtitle_size_tolerance=max(0, settings.subtitle_size_tolerance) / 100,
        debug=settings.debug,
        dump_dir=settings.dump_dir or None,
    )


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


# Translators for trying the pipeline without a key or a network.
_DUMMY_TRANSLATORS = {"uppercase": UppercaseTranslator, "verbose": VerboseTranslator, "echo": EchoTranslator}


def build_translator(settings: Settings, game: str, store: ProfileStore, secrets: SecretStore) -> Translator:
    if dummy := _DUMMY_TRANSLATORS.get(settings.translator):
        return dummy()
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
        api_key=anthropic_api_key(secrets),
    )


def _spread(values: Iterable[float]) -> str:
    ordered = sorted(values)
    return f"median {ordered[len(ordered) // 2]:.0f}ms min {ordered[0]:.0f}ms max {ordered[-1]:.0f}ms"


class StartError(RuntimeError):
    """A start that cannot go ahead, with a message fit for the status line."""


@dataclass(slots=True)
class Prepared:
    """Everything start() needs that takes time to obtain, gathered off the
    UI thread: the window, the translators, the OCR engine and the pipeline
    configuration. `generation` tells a stale result from the current one."""

    generation: int
    hwnd: int
    title: str
    settings: Settings
    game: str
    translator: Translator
    draft: Translator | None
    engine: RapidOcrEngine
    config: PipelineConfig


class _StartWorker(QThread):
    """Runs `OverlayController.prepare` away from the UI thread, so the tray
    and the settings window stay responsive while the window is waited for
    and the models load (or download, on first use)."""

    progress = Signal(str)
    prepared = Signal(object)  # Prepared
    failed = Signal(int, str)  # generation, message

    def __init__(
        self, controller: OverlayController, generation: int, settings: Settings, hwnd: int | None, wait: float
    ) -> None:
        super().__init__(controller)
        self.controller = controller
        self.generation = generation
        self.settings = settings
        self.hwnd = hwnd
        self.wait_seconds = wait

    def run(self) -> None:
        try:
            result = self.controller.prepare(
                self.settings, self.hwnd, self.wait_seconds, self.progress.emit, self.generation
            )
        except StartError as exc:
            self.failed.emit(self.generation, str(exc))
        except Exception as exc:  # anything unforeseen still reaches the status line
            self.failed.emit(self.generation, f"start failed: {type(exc).__name__}: {exc}")
        else:
            self.prepared.emit(result)


class OverlayController(QObject):
    """Owns the OCR engine, translation service, overlay window and pipeline
    thread for one running session; start() tears down any previous one.

    start() returns at once: the slow part (waiting for the window, building
    the translators, loading the OCR engine) runs on a thread, and the
    session begins when it is done. `running_changed(True)` or
    `start_failed(message)` reports the outcome."""

    status = Signal(str)
    running_changed = Signal(bool)
    starting_changed = Signal(bool)  # True while start() is being prepared on its thread
    paused_changed = Signal(bool)
    start_failed = Signal(str)
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
        self._engines: dict[tuple[str, bool], RapidOcrEngine] = {}  # by (language, gpu)
        self._engine_lock = threading.Lock()
        self._generation = 0  # bumped by every start() and stop(); a preparation from before is ignored
        self._start_workers: set[_StartWorker] = set()
        self._starting = False
        self._selector: AreaSelector | None = None
        self._selection: tuple[int, Box, Box | None] | None = None  # window, frame, client of the open selector

    # -- state -------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self.worker is not None

    @property
    def starting(self) -> bool:
        """A start() is being prepared and has not yet become running or failed."""
        return self._starting

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

    def engine(self, lang: str, gpu: bool, frame_w: int, frame_h: int, say: Callable[[str], None]) -> RapidOcrEngine:
        """One warmed-up OCR engine per language and device, kept for the
        life of the controller (loading takes a second or two). Safe to call
        from a worker thread; two starts wanting the same engine load it once."""
        with self._engine_lock:
            engine = self._engines.get((lang, gpu))
            if engine is None:
                device = "GPU" if gpu else "CPU"
                say(f"loading OCR model ({lang}, {device})... first use downloads it")
                engine = RapidOcrEngine(lang=lang, use_dml=gpu, model_root_dir=str(self.store.models_dir / "ocr"))
                engine.warm_up(frame_w, frame_h)
                self._engines[(lang, gpu)] = engine
        return engine

    def start(self, settings: Settings, hwnd: int | None = None, wait: float = 0.0) -> bool:
        """Begin a session on the window `settings` (or `hwnd`) names. False
        when the licence forbids it; otherwise True, and the outcome arrives
        as `running_changed(True)` or `start_failed(message)`."""
        licence = license_status(self.secrets, self.store)
        if not licence.may_run:
            self._say(f"{licence.text}: enter one in Settings > Licence")
            return False
        if self.running:
            self.stop()
        self._generation += 1
        self._starting = True
        self.starting_changed.emit(True)
        worker = _StartWorker(self, self._generation, settings.copy(), hwnd, wait)
        worker.progress.connect(self._say)
        worker.prepared.connect(self._on_prepared)
        worker.failed.connect(self._on_start_failed)
        worker.finished.connect(lambda: self._start_workers.discard(worker))
        self._start_workers.add(worker)
        target = f"window {hwnd:#x}" if hwnd else f"{settings.window_match!r}"
        self._say(f"starting on {target}...")
        worker.start()
        return True

    def prepare(
        self,
        settings: Settings,
        hwnd: int | None,
        wait: float,
        say: Callable[[str], None],
        generation: int = 0,
    ) -> Prepared:
        """The slow, thread-safe part of start(): find the window (waiting up
        to `wait` seconds), build the translators, load the OCR engine and
        work out the pipeline configuration. Raises StartError with a message
        for the status line when the session cannot begin."""
        resolved = self.resolve_window(settings, hwnd, wait)
        if resolved is None:
            raise StartError(f"no visible window matching {settings.window_match!r}")
        hwnd, title = resolved
        game = settings.game or title or "game"

        if settings.translator == "claude" and not has_anthropic_credentials(self.secrets):
            raise StartError("no Anthropic key: enter one in Settings > Translation")
        try:
            translator = build_translator(settings, game, self.store, self.secrets)
            draft = build_draft_translator(settings, self.store, self.secrets)
        except (OSError, ValueError, RuntimeError, ImportError) as exc:
            raise StartError(f"translator setup failed: {exc}") from exc
        for candidate in (translator, draft):
            if getattr(candidate, "kind", None):
                say(f"offline model: {candidate.kind} ({candidate.model_dir})")  # type: ignore[union-attr]

        frame, client = capture_area(hwnd, settings.include_frame)
        try:
            config = pipeline_config(settings, frame, client)
        except re.error as exc:
            raise StartError(f"invalid ignore pattern: {exc}") from exc
        try:
            engine = self.engine(settings.lang, settings.ocr_gpu, frame[2], frame[3], say)
        except Exception as exc:
            raise StartError(f"OCR engine failed to load: {type(exc).__name__}: {exc}") from exc
        return Prepared(generation, hwnd, title, settings, game, translator, draft, engine, config)

    def _settled(self) -> None:
        """The start in progress has reached its outcome, whichever it is."""
        if self._starting:
            self._starting = False
            self.starting_changed.emit(False)

    def _on_prepared(self, prepared: Prepared) -> None:
        if prepared.generation != self._generation or self.running:
            return  # a later start() or stop() superseded this one
        self._settled()
        try:
            self.hwnd, self.title, self.settings = prepared.hwnd, prepared.title, prepared.settings
            self.translator = prepared.translator
            self.service = self._build_service(prepared.settings, prepared.game, prepared.translator, prepared.draft)
            if self.cache is not None and self.cache.load_error:
                self._say(f"translation cache unreadable ({self.cache.load_error}): set aside as .bad, starting empty")
            self.overlay = OverlayWindow(
                prepared.hwnd,
                hide_when_unfocused=prepared.settings.hide_when_unfocused,
                exclude_from_capture=prepared.settings.exclude_from_capture,
                font_family=prepared.settings.font,
            )
            worker = PipelineThread(prepared.hwnd, prepared.engine, self.service, prepared.config)
            worker.blocks_ready.connect(self.overlay.set_blocks)
            worker.status.connect(self._say)
            worker.finished.connect(lambda: self._on_worker_finished(worker))
            self.overlay.target_lost.connect(self._on_target_lost)
            self.worker = worker
            self.overlay.start()
            worker.start()
        except Exception as exc:
            self._release()  # undo what was built before the failure
            self._fail(f"start failed: {type(exc).__name__}: {exc}")
            return
        self.running_changed.emit(True)
        self._say(
            f"running on {self.title!r}: {prepared.settings.effective_source_lang} -> "
            f"{prepared.settings.target_lang} via {prepared.translator.name}"
        )

    def _on_start_failed(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self._settled()
        self._fail(message)

    def _fail(self, message: str) -> None:
        self._say(message)
        self.start_failed.emit(message)

    def _release(self) -> None:
        """Let go of the session's overlay and translation service (the
        pipeline thread, if any, has been stopped by the caller)."""
        overlay, service = self.overlay, self.service
        self.worker, self.overlay, self.service = None, None, None
        if overlay is not None:
            overlay.close()
            overlay.deleteLater()
        if service is not None:
            service.shutdown()

    def _on_worker_finished(self, worker: PipelineThread) -> None:
        """The pipeline thread ended on its own (capture closed, or an error
        it has already reported): the session is over."""
        if self.worker is worker:
            self._say("pipeline stopped")
            self.stop()

    def _build_service(
        self, settings: Settings, game: str, translator: Translator, draft: Translator | None
    ) -> TranslationService:
        path = self.store.cache_path(game, settings.target_lang, translator.name) if settings.use_cache_file else None
        self.cache = TranslationCache(path)
        return TranslationService(
            translator,
            self.cache,
            target_lang=settings.target_lang,
            source_lang=settings.effective_source_lang,
            on_status=self._say,
            draft_translator=draft,
            autosave_seconds=settings.autosave_seconds,
        )

    def _on_target_lost(self) -> None:
        self._say("game window closed")
        self.stop()

    def stop(self) -> None:
        """End the session; a start() still being prepared is abandoned."""
        self._generation += 1
        self._settled()
        worker = self.worker
        if worker is not None:
            worker.stop()
            worker.wait(3000)
        self._release()
        self.running_changed.emit(False)
        self.paused_changed.emit(False)
        self._say("stopped")

    def close(self, wait_ms: int = 5000) -> None:
        """stop(), then let any start still being prepared run out, so the
        process does not tear down a thread that is loading a model."""
        self.stop()
        for worker in list(self._start_workers):
            worker.wait(wait_ms)

    def toggle(self, settings: Settings) -> None:
        if self.running or self.starting:
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
        frame, client = capture_area(hwnd, active.include_frame)
        self._selection = (hwnd, frame, client)
        ax0, _, ax1, _ = client or frame
        selector = AreaSelector(window_rect(hwnd), mirror_x=active.center_zone, center_x=(ax0 + ax1) // 2)
        selector.selected.connect(self._apply_selected_area)
        selector.cancelled.connect(self._selection_cancelled)
        # Closed any other way (the layer deletes itself on close): forget it,
        # or no selection could ever be started again.
        selector.destroyed.connect(lambda *_: self._forget_selector(selector))
        self._selector = selector
        selector.start()
        self._say("drag to select the area to translate (Esc cancels)")
        return True

    def _forget_selector(self, selector: AreaSelector) -> None:
        if self._selector is selector:
            self._selector = None

    def _selection_cancelled(self) -> None:
        self._selector = None
        self._say("area selection cancelled")

    def _apply_selected_area(self, rect: tuple) -> None:
        self._selector = None
        assert self._selection is not None
        # The same frame and client area the selector was opened over: the
        # settings in force may have changed meanwhile, or not exist yet.
        hwnd, frame, client = self._selection
        spec = rect_to_zone_spec(tuple(rect), client or frame)
        self._say(f"area selected: {spec}; translating only that area")
        self._set_area(spec, hwnd)

    def clear_area(self) -> None:
        self._say("area cleared: translating the whole window")
        self._set_area("", self.hwnd)

    def _set_area(self, spec: str, hwnd: int | None) -> None:
        """Make `spec` the area of the session's settings and tell the
        owner; a running session restarts on it."""
        if self.settings is not None:
            self.settings.set_area(spec)
        self.area_selected.emit(spec)
        if self.running and self.settings is not None:
            self.start(self.settings, hwnd)

    # -- reporting ---------------------------------------------------------

    def stats_text(self) -> str:
        parts = []
        if self.worker and self.worker.ocr_ms:
            parts.append(
                f"frames {self.worker.frames} read, {self.worker.skipped} unchanged, ocr {_spread(self.worker.ocr_ms)}"
            )
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
