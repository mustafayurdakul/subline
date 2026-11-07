"""Builds and runs the overlay from a Settings object. Shared by the command
line, the tray icon and the settings window."""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ..capture.windows import (
    client_rect_on_screen,
    find_window,
    is_minimized,
    is_window,
    window_rect,
    window_title,
)
from ..geometry import RGB, Box
from ..ocr.rapid import RapidOcrEngine
from ..overlay.selector import AreaSelector, rect_to_zone_spec
from ..overlay.window import OverlayWindow
from ..tracking.filters import LineFilter
from ..translate.base import Translator
from ..translate.cache import TranslationCache
from ..translate.dummy import EchoTranslator, UppercaseTranslator, VerboseTranslator
from ..translate.service import TranslationService
from .config import DRAFTS, TRANSLATORS, ProfileStore, Settings
from .credentials import (
    DEEPL_KEY,
    SecretStore,
    WindowsCredentialStore,
    anthropic_api_key,
    has_anthropic_credentials,
    resolve_key,
)
from .pipeline import PipelineConfig, PipelineThread

# -- zones and colours -------------------------------------------------------------


def _zone_numbers(spec: str) -> tuple[float, float, float, float] | None:
    """The numbers of 'x,y,w,h', or None when `spec` is not four finite numbers."""
    try:
        numbers = tuple(float(v) for v in spec.split(","))
    except ValueError:
        return None
    if len(numbers) != 4 or not all(math.isfinite(v) for v in numbers):
        return None
    return numbers[0], numbers[1], numbers[2], numbers[3]


def zone_problem(spec: str, what: str = "area") -> str | None:
    """Why `spec`, an area or an ignore zone (`what` names it in the
    message), cannot be read; None when it can or is empty. A zone is four
    numbers x,y,w,h with a width and a height above 0."""
    if not spec.strip():
        return None
    numbers = _zone_numbers(spec)
    if numbers is None:
        return f"{what} {spec!r}: expected x,y,w,h"
    if numbers[2] <= 0 or numbers[3] <= 0:
        return f"{what} {spec!r}: the width and the height must be above 0"
    return None


def parse_zone(spec: str | None, width: int, height: int) -> Box | None:
    """'x,y,w,h' as fractions (all <= 1) or pixels -> (x0, y0, x1, y1),
    clamped to `width` x `height`. None when `spec` is empty or cannot be
    read (see zone_problem), or when nothing of it lies inside."""
    numbers = _zone_numbers(spec) if spec else None
    if numbers is None:
        return None
    x, y, w, h = numbers
    if max(x, y, w, h) <= 1.0:
        x, y, w, h = x * width, y * height, w * width, h * height
    # Rounded, not truncated: fractions saved with four decimals land a hair
    # under the pixel they came from, and truncation would lose that pixel.
    x0, y0, x1, y1 = max(0, round(x)), max(0, round(y)), min(width, round(x + w)), min(height, round(y + h))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


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
    pipeline wants frame pixels.

    Raises ValueError for an area or an ignore zone that cannot be read, and
    for an area with nothing inside the window: read as no area, it would
    have the whole window read and translated. re.error for an invalid
    ignore pattern."""
    for spec, what in [(settings.roi, "area"), *((zone, "ignore zone") for zone in settings.ignore_zones)]:
        if problem := zone_problem(spec, what):
            raise ValueError(problem)
    ax0, ay0, ax1, ay1 = client or frame
    width, height = ax1 - ax0, ay1 - ay0
    roi = parse_zone(settings.roi, width, height)
    if roi is None and settings.roi.strip():
        raise ValueError(f"area {settings.roi!r} lies outside the game's picture")
    zones = (parse_zone(spec, width, height) for spec in settings.ignore_zones)
    ignore_zones = [offset_zone(zone, ax0, ay0) for zone in zones if zone is not None]  # one outside hides nothing
    patterns = [p for p in settings.ignore_patterns if p.strip()]
    return PipelineConfig(
        frame_size=(frame[2] - frame[0], frame[3] - frame[1]),
        area=client,
        roi=offset_zone(roi, ax0, ay0) if roi is not None else None,
        fps=settings.fps,
        full_scan_every=settings.full_scan_every,
        stable_frames=settings.stable_frames,
        max_missing=settings.max_missing,
        change_threshold=settings.change_threshold,
        style=settings.style,
        line_filter=LineFilter.compile(ignore_zones, patterns, short_confidence=settings.short_line_confidence),
        render=settings.render,
        subtitle_font_px=settings.subtitle_font_px,
        subtitle_color=parse_color(settings.subtitle_color) if settings.subtitle_color.strip() else None,
        subtitle_background=settings.subtitle_background,
        subtitle_pill_alpha=settings.subtitle_pill_alpha,
        subtitle_weight=settings.subtitle_weight,
        subtitle_position=settings.subtitle_position,
        subtitle_hide_source=settings.subtitle_hide_source,
        subtitle_center_tolerance=max(0, settings.subtitle_center_tolerance) / 100,
        subtitle_size_tolerance=max(0, settings.subtitle_size_tolerance) / 100,
        debug=settings.debug,
        dump_dir=settings.dump_dir or None,
    )


# -- translators ---------------------------------------------------------------------


class StartError(Exception):
    """A start that cannot go ahead, with a message fit for the status line."""


# The translators that translate nothing, for trying the pipeline without a key or a network.
_DUMMY_TRANSLATORS = {"uppercase": UppercaseTranslator, "verbose": VerboseTranslator, "echo": EchoTranslator}


def translator_name(settings: Settings) -> str:
    """The translator `settings` names, as build_translator reads it."""
    return settings.translator.strip().lower()


def draft_name(settings: Settings) -> str:
    """The draft `settings` names, read the same way ("" for none)."""
    return settings.draft.strip().lower()


def check_translator(settings: Settings, secrets: SecretStore) -> None:
    """Refuse at once, before any waiting or loading, a translator or draft
    that does not exist or has no key to work with. Raises StartError."""
    name = translator_name(settings)
    if name not in TRANSLATORS:
        raise StartError(f"unknown translator {settings.translator!r}")
    if draft_name(settings) not in DRAFTS:
        raise StartError(f"unknown draft {settings.draft!r}")
    if "deepl" in (name, draft_name(settings)) and resolve_key(DEEPL_KEY, secrets) is None:
        raise StartError("Add your DeepL key on the Translation page")
    if name == "claude" and not has_anthropic_credentials(secrets):
        raise StartError("Add your Anthropic key on the Translation page")


def build_offline_translator(settings: Settings, store: ProfileStore) -> Translator:
    from ..translate.offline import OfflineTranslator, activate_runtime

    activate_runtime(store.runtime_dir)
    return OfflineTranslator.from_models_dir(store.models_dir, settings.effective_source_lang, settings.target_lang)


def build_deepl_translator(secrets: SecretStore) -> Translator:
    from ..translate.deepl import DeepLTranslator

    found = resolve_key(DEEPL_KEY, secrets)
    return DeepLTranslator(auth_key=found[0] if found else None)


def build_draft_translator(settings: Settings, store: ProfileStore, secrets: SecretStore) -> Translator | None:
    draft = draft_name(settings)
    if not draft or draft == translator_name(settings):
        return None
    if draft == "offline":
        return build_offline_translator(settings, store)
    return build_deepl_translator(secrets)  # check_translator has refused any other name


def build_translator(settings: Settings, game: str, store: ProfileStore, secrets: SecretStore) -> Translator:
    """The translator `settings` names. Raises StartError for a name it does
    not know: a misspelt name must never fall through to a paid service."""
    name = translator_name(settings)
    if dummy := _DUMMY_TRANSLATORS.get(name):
        return dummy()
    if name == "offline":
        return build_offline_translator(settings, store)
    if name == "deepl":
        return build_deepl_translator(secrets)
    if name == "claude":
        return build_claude_translator(settings, game, secrets)
    raise StartError(f"unknown translator {settings.translator!r}")


def build_claude_translator(settings: Settings, game: str, secrets: SecretStore) -> Translator:
    from ..translate.claude import ClaudeTranslator

    glossary = None
    # Explorer's "Copy as path" puts the path in double quotes, and a pasted path often brings a space along.
    glossary_path = settings.glossary_path.strip().strip('"').strip()
    if glossary_path:
        with open(glossary_path, encoding="utf-8") as fh:
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


# Settings a running session cannot take up on the fly: a change in one of
# them restarts the session. Everything else (the area, the filters, the
# timing, the look) reaches the pipeline and the overlay as they run.
SESSION_FIELDS = frozenset(
    {
        "window_match", "game", "include_frame", "lang", "ocr_gpu", "source_lang", "target_lang", "translator",
        "draft", "model", "effort", "thinking", "structured", "glossary_path", "tone", "use_cache_file", "fps",
        "autosave_seconds",
    }
)  # fmt: skip
# Of those, the ones only Claude reads: a session without Claude is not restarted for them.
CLAUDE_FIELDS = frozenset({"model", "effort", "thinking", "structured", "tone", "glossary_path"})


def restart_fields(settings: Settings) -> frozenset[str]:
    """The SESSION_FIELDS whose change restarts a session run with `settings`."""
    if translator_name(settings) == "claude":  # a draft is never Claude
        return SESSION_FIELDS
    return SESSION_FIELDS - CLAUDE_FIELDS


@dataclass(slots=True)
class Prepared:
    """Everything start() needs that takes time to obtain, gathered off the
    UI thread: the window, the translators, the translation cache, the OCR
    engine and the pipeline configuration. `generation` tells a stale result
    from the current one."""

    generation: int
    hwnd: int
    title: str
    settings: Settings
    translator: Translator
    draft: Translator | None
    cache: TranslationCache
    engine: RapidOcrEngine
    config: PipelineConfig


class _StartWorker(QThread):
    """Runs `OverlayController.prepare` away from the UI thread, so the tray
    and the settings window stay responsive while the window is waited for
    and the models load (or download, on first use).

    It has no Qt parent: the controller holds it only until it finishes, so
    the object goes then, not with the controller (one would be left behind
    by every start, edit-triggered restarts included)."""

    progress = Signal(str)
    prepared = Signal(object)  # Prepared
    failed = Signal(int, str)  # generation, message

    def __init__(
        self, controller: OverlayController, generation: int, settings: Settings, hwnd: int | None, wait: float
    ) -> None:
        super().__init__()
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
        # Stopped pipeline threads, held until their `finished` arrives: freed
        # earlier, a new thread can take the old one's address and be taken for it.
        self._retiring: set[PipelineThread] = set()
        self._engines: dict[tuple[str, bool], RapidOcrEngine] = {}  # by (language, gpu)
        self._engine_lock = threading.Lock()
        self._generation = 0  # bumped by every start() and stop(); a preparation from before is ignored
        self._start_workers: set[_StartWorker] = set()
        self._starting = False
        self._requested_hwnd: int | None = None  # the handle the start in progress was given...
        self._requested_match = ""  # ...for the window title it was asked to match...
        self._start_deadline = 0.0  # ...and until when (time.monotonic()) it may wait for that window
        self._selector: AreaSelector | None = None
        self._selection: tuple[int, Box, Box | None] | None = None  # window, frame, client of the open selector
        self.last_stats = ""  # stats_text() of the last session, kept when it stops

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

    def resolve_window(
        self,
        settings: Settings,
        hwnd: int | None = None,
        wait: float = 0.0,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, str] | None:
        """The window to run on: `hwnd` while it still exists (a handle
        picked from a list goes stale when the game restarts), else the first
        window whose title holds `settings.window_match`, waiting up to `wait`
        seconds for one to appear, or until `cancelled()` turns true.

        A live handle is trusted whatever its title says now: many games and
        emulators put a frame counter or the level's name in it, so the title
        picked from the list is soon out of date. A pick of another window
        reaches here without the handle (see apply() and the settings backend)."""
        if hwnd and is_window(hwnd):
            return hwnd, window_title(hwnd)
        if not settings.window_match:
            return None
        deadline = time.perf_counter() + wait
        info = find_window(settings.window_match)
        while info is None and time.perf_counter() < deadline and not (cancelled and cancelled()):
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

    def start(self, settings: Settings, hwnd: int | None = None, wait: float = 0.0) -> None:
        """Begin a session on the window `settings` (or `hwnd`) names; the
        outcome arrives as `running_changed(True)` or `start_failed(message)`."""
        if self.running:
            self.stop()
        self._generation += 1
        self._starting = True
        self._requested_hwnd, self._requested_match = hwnd, settings.window_match
        self._start_deadline = time.monotonic() + wait
        self.starting_changed.emit(True)
        worker = _StartWorker(self, self._generation, settings.copy(), hwnd, wait)
        worker.progress.connect(self._say)
        worker.prepared.connect(self._on_prepared)
        worker.failed.connect(self._on_start_failed)
        worker.finished.connect(self._on_start_worker_finished)
        self._start_workers.add(worker)
        target = f"window {hwnd:#x}" if hwnd else f"{settings.window_match!r}"
        self._say(f"starting on {target}...")
        worker.start()

    def prepare(
        self,
        settings: Settings,
        hwnd: int | None,
        wait: float,
        say: Callable[[str], None],
        generation: int,
    ) -> Prepared:
        """The slow, thread-safe part of start(): find the window (waiting up
        to `wait` seconds), build the translators, read the translation
        cache, load the OCR engine and work out the pipeline configuration.
        Raises StartError with a message for the status line when the
        session cannot begin; a missing key is reported before any wait."""
        check_translator(settings, self.secrets)
        # A later start() or stop() ends the wait: quitting must not sit out the rest of it.
        resolved = self.resolve_window(settings, hwnd, wait, cancelled=lambda: generation != self._generation)
        if resolved is None:
            if hwnd and not settings.window_match:
                raise StartError(f"window {hwnd:#x} is gone")
            raise StartError(f"no visible window matching {settings.window_match!r}")
        hwnd, title = resolved
        # Not the title first: many games and emulators put a frame counter in it, which would
        # name a new cache file at every start.
        game = settings.game or settings.window_match or title or "game"

        try:
            translator = build_translator(settings, game, self.store, self.secrets)
            draft = build_draft_translator(settings, self.store, self.secrets)
        except (OSError, ValueError, RuntimeError, ImportError) as exc:
            raise StartError(f"translator setup failed: {exc}") from exc
        for candidate in (translator, draft):
            if getattr(candidate, "kind", None):
                say(f"offline model: {candidate.kind} ({candidate.model_dir})")  # type: ignore[union-attr]
        # Read here, off the UI thread: a pre-translated script makes a cache of tens of thousands of lines.
        path = self._cache_path(settings, game, title, translator.name) if settings.use_cache_file else None
        cache = TranslationCache(path)

        frame, client = capture_area(hwnd, settings.include_frame)
        try:
            config = pipeline_config(settings, frame, client)
        except re.error as exc:
            raise StartError(f"invalid ignore pattern: {exc}") from exc
        except ValueError as exc:
            raise StartError(str(exc)) from exc
        try:
            engine = self.engine(settings.lang, settings.ocr_gpu, frame[2], frame[3], say)
        except Exception as exc:
            raise StartError(f"OCR engine failed to load: {type(exc).__name__}: {exc}") from exc
        return Prepared(generation, hwnd, title, settings, translator, draft, cache, engine, config)

    def _cache_path(self, settings: Settings, game: str, title: str, translator: str) -> Path:
        """The translation cache file for `game`. Without a Game name, a file
        named after the window title is used while there is none for `game`:
        earlier versions named the file after the title then, and the
        translations in it are kept."""
        path = self.store.cache_path(game, settings.target_lang, translator)
        if settings.game or path.exists():
            return path
        by_title = self.store.cache_path(title, settings.target_lang, translator)
        return by_title if by_title.exists() else path

    def _on_start_worker_finished(self) -> None:
        """A start thread has ended (its result, queued before, has arrived):
        the last reference to it goes, and with it the thread object."""
        self._start_workers.discard(self.sender())  # type: ignore[arg-type]

    def _end_starting(self) -> None:
        """The start in progress has reached its outcome, whichever it is."""
        if self._starting:
            self._starting = False
            self.starting_changed.emit(False)

    def _on_prepared(self, prepared: Prepared) -> None:
        if prepared.generation != self._generation:
            return  # a later start() or stop() superseded this one
        self._end_starting()
        try:
            self.hwnd, self.title, self.settings = prepared.hwnd, prepared.title, prepared.settings
            self.service = self._build_service(prepared.settings, prepared.translator, prepared.draft, prepared.cache)
            self._report_cache_problem(prepared.cache)
            self.overlay = OverlayWindow(
                prepared.hwnd,
                hide_when_unfocused=prepared.settings.hide_when_unfocused,
                exclude_from_capture=prepared.settings.exclude_from_capture,
                font_family=prepared.settings.font,
            )
            worker = PipelineThread(prepared.hwnd, prepared.engine, self.service, prepared.config)
            worker.blocks_ready.connect(self.overlay.set_blocks)
            worker.status.connect(self._say)
            worker.resized.connect(self._on_frame_resized)
            worker.finished.connect(self._on_worker_finished)  # a lambda holding `worker` would keep it forever
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

    def _report_cache_problem(self, cache: TranslationCache) -> None:
        """Say why the translation cache file could not be read, if it could not."""
        if not cache.load_error:
            return
        if cache.set_aside:
            self._say(f"translation cache unreadable ({cache.load_error}): set aside as .bad, starting empty")
        else:
            self._say(
                f"could not read the translation cache ({cache.load_error}): this session's translations are not saved"
            )

    def _on_start_failed(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self._end_starting()
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

    def _on_worker_finished(self) -> None:
        """A pipeline thread has ended. The session's own ended on its own
        (capture closed, or an error it has already reported): the session
        is over. Either way the last reference to the thread goes."""
        worker = self.sender()
        if worker is self.worker:
            self._say("pipeline stopped")
            self.stop()
        self._retiring.discard(worker)  # type: ignore[arg-type]  # after stop(), which adds it

    def _build_service(
        self, settings: Settings, translator: Translator, draft: Translator | None, cache: TranslationCache
    ) -> TranslationService:
        return TranslationService(
            translator,
            cache,
            target_lang=settings.target_lang,
            source_lang=settings.effective_source_lang,
            on_status=self._say,
            draft_translator=draft,
            autosave_seconds=settings.autosave_seconds,
        )

    def _on_target_lost(self) -> None:
        self._say("game window closed")
        self.stop()

    def _on_frame_resized(self) -> None:
        """The captured frames changed size: the window was resized, or the
        game changed resolution or went full screen. The area read and the
        zones are frame pixels, so they are worked out again for the new size."""
        if self.running and self.settings is not None:
            self.apply(self.settings)

    def stop(self) -> None:
        """End the session; a start() still being prepared is abandoned.
        Nothing happens when there is neither."""
        if not (self.running or self.starting):
            return
        self._generation += 1
        self._end_starting()
        worker = self.worker
        if worker is not None:  # the service comes and goes with it
            worker.stop()
            worker.wait(3000)
            # Kept until its `finished` arrives: that is queued even when the wait saw the thread
            # end, and a thread that outlived the wait must not be destroyed while it runs.
            self._retiring.add(worker)
            self.last_stats = self.stats_text()  # the session's numbers, before they are let go
        self._release()
        self.running_changed.emit(False)
        self.paused_changed.emit(False)
        self._say("stopped")

    def apply(self, settings: Settings) -> None:
        """Settings edited while a session runs or starts. The area, the
        filters, the timing and the look take effect at once; a change of
        window, language or translator restarts the session on them."""
        if self.starting:
            # The handle the start was given still holds unless the edit names another window,
            # and so does what is left of the time it was given to wait for the window.
            same_window = settings.window_match == self._requested_match
            wait = max(0.0, self._start_deadline - time.monotonic())
            self.start(settings, self._requested_hwnd if same_window else None, wait)
            return
        if not self.running or self.settings is None:
            return
        assert self.worker is not None and self.overlay is not None and self.hwnd is not None
        if any(getattr(settings, name) != getattr(self.settings, name) for name in restart_fields(settings)):
            same_window = settings.window_match == self.settings.window_match
            self._say("settings changed: restarting")
            self.start(settings, self.hwnd if same_window else None)
            return
        frame, client = capture_area(self.hwnd, settings.include_frame)
        try:
            config = pipeline_config(settings, frame, client)
        except re.error as exc:
            self._say(f"invalid ignore pattern: {exc}")
            return
        except ValueError as exc:
            self._say(str(exc))
            return
        self.worker.update_config(config)
        self.overlay.apply(settings.font, settings.hide_when_unfocused, settings.exclude_from_capture)
        self.settings = settings

    def close(self) -> None:
        """stop(), then let every thread still running run out, so the
        process does not tear down a thread that is loading a model: a start
        still being prepared (its wait for the window ends at once, a model
        load or download does not), or a pipeline thread that outlived stop()."""
        self.stop()
        for worker in [*self._start_workers, *self._retiring]:
            worker.wait()

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

    def select_area(self, settings: Settings | None = None) -> None:
        """Open the drag-to-select layer over the game window. The result
        becomes the only area read and translated; a running session takes
        it up from the next frame. Uses the running window, else the one
        `settings` names. A layer already open is brought to the front."""
        if self._selector is not None:
            self._selector.start()
            return
        active = settings or self.settings or Settings()
        hwnd = self.hwnd
        if hwnd is None or not self.running:
            resolved = self.resolve_window(active)
            if resolved is None:
                self._say("select area: no game window found; start the game or set its title first")
                return
            hwnd = resolved[0]
        if is_minimized(hwnd):
            # Windows reports a minimized window as a small box far off screen: the layer would open there, unseen.
            self._say("select area: restore the game window first")
            return
        frame, client = capture_area(hwnd, active.include_frame)
        self._selection = (hwnd, frame, client)
        ax0, _, ax1, _ = client or frame
        selector = AreaSelector(window_rect(hwnd), mirror_x=active.center_area, center_x=(ax0 + ax1) // 2)
        selector.selected.connect(self._apply_selected_area)
        selector.cancelled.connect(self._selection_cancelled)
        # Closed any other way (the layer deletes itself on close): forget it,
        # or no selection could ever be started again.
        selector.destroyed.connect(lambda *_: self._forget_selector(selector))
        self._selector = selector
        selector.start()
        self._say("drag to select the area to translate (Esc cancels)")

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
        if spec is None:  # dragged on the title bar or the frame alone: the area in force stays
            self._say("area selection: the area lies outside the game's picture")
            return
        self._say(f"area selected: {spec}; translating only that area")
        self._set_area(spec, hwnd)

    def clear_area(self) -> None:
        self._say("area cleared: translating the whole window")
        self._set_area("", self.hwnd)

    def _set_area(self, spec: str, hwnd: int | None) -> None:
        """Make `spec` the area of the session's settings and tell the
        owner; a running session reads the new area from the next frame."""
        if self.settings is not None:
            self.settings.roi = spec
        self.area_selected.emit(spec)
        if self.running and self.settings is not None and hwnd == self.hwnd:
            self.apply(self.settings)

    # -- reporting ---------------------------------------------------------

    def stats_text(self) -> str:
        parts = []
        if self.worker and self.worker.ocr_ms:
            parts.append(
                f"frames {self.worker.frames} read, {self.worker.skipped} unchanged, ocr {_spread(self.worker.ocr_ms)}"
            )
        if self.service:
            st = self.service.stats
            parts.append(
                f"translation: {st['requests']} requests, {st['items']} items sent, {st['translated']} translated, "
                f"{st['cache_hits']} cache hits, {st['errors']} errors; cache {len(self.service.cache)} entries"
            )
            if self.service.latencies_ms:
                parts.append(f"request latency: {_spread(self.service.latencies_ms)}")
            if self.service.draft_latencies_ms:
                parts.append(f"draft: {st['drafts']} items, latency {_spread(self.service.draft_latencies_ms)}")
            translator = self.service.translator
            totals = getattr(translator, "usage_totals", None)
            calls = getattr(translator, "calls", 0)
            if totals and calls and self.settings:
                from ..translate.claude import estimate_cost_usd

                cost = estimate_cost_usd(self.settings.model, totals)
                cost_text = f" ~${cost:.5f}" if cost is not None else ""
                parts.append(
                    f"tokens: {totals['input']} in, {totals['output']} out, {totals['cache_read']} cache read, "
                    f"{totals['cache_write']} cache write over {calls} calls{cost_text}"
                )
        return "\n".join(parts)


def _spread(values: Iterable[float]) -> str:
    """Median, low and high of a set of timings, for stats_text."""
    ordered = sorted(values)
    return f"median {ordered[len(ordered) // 2]:.0f}ms min {ordered[0]:.0f}ms max {ordered[-1]:.0f}ms"
