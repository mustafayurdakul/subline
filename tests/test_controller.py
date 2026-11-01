"""OverlayController lifecycle with fakes for the window, the capture, the
OCR engine and the overlay: start on a thread, stop, restart on an area
selection, a pipeline that dies, and starts that cannot go ahead."""

from __future__ import annotations

import os
import threading
import time
import weakref
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication

from gametl.app import controller as controller_module
from gametl.app import pipeline as pipeline_module
from gametl.app.config import ProfileStore, Settings
from gametl.app.controller import (
    CLAUDE_FIELDS,
    SESSION_FIELDS,
    OverlayController,
    StartError,
    build_translator,
    pipeline_config,
    restart_fields,
)
from gametl.app.credentials import MemorySecretStore
from gametl.capture.base import Frame
from gametl.capture.windows import WindowInfo
from gametl.ocr.base import OcrResult, TextLine
from gametl.translate.cache import TranslationCache
from gametl.translate.dummy import UppercaseTranslator
from tests.helpers import wait_until

HWND = 4242
TITLE = "Fake Game"
FRAME = (0, 0, 800, 600)
CLIENT = (0, 30, 800, 600)


def wait_for(qapp: QApplication, predicate, timeout: float = 5.0) -> None:
    assert wait_until(predicate, timeout, tick=qapp.processEvents), "condition not met in time"


class FakeEngine:
    name = "fake"
    created: list[FakeEngine] = []
    delay = 0.0  # seconds the "model load" takes

    def __init__(self, **_kwargs) -> None:
        time.sleep(self.delay)
        FakeEngine.created.append(self)
        self.calls = 0

    def warm_up(self, width: int, height: int) -> float:
        return 0.0

    def recognize(self, image_bgr: np.ndarray) -> OcrResult:
        self.calls += 1
        quad = np.array([[300, 500], [700, 500], [700, 540], [300, 540]], dtype=np.float32)
        return OcrResult(lines=[TextLine("Stay close.", quad, 0.95)])


class FakeCapture:
    """Hands out a blank frame every few milliseconds; `fail` makes the
    pipeline thread die, `closed` ends it as a closed window would, `size`
    is the frames' (width, height)."""

    fail = False
    close = False
    size = (FRAME[2], FRAME[3])

    def __init__(self, hwnd: int, min_interval_ms: int | None = None) -> None:
        self.hwnd = hwnd
        self.closed = False

    def __enter__(self) -> FakeCapture:
        return self

    def __exit__(self, *exc) -> None:
        pass

    def next_frame(self, timeout: float | None = None) -> Frame | None:
        time.sleep(0.01)
        if FakeCapture.fail:
            raise RuntimeError("capture exploded")
        if FakeCapture.close:
            self.closed = True
            return None
        width, height = FakeCapture.size
        return Frame(np.full((height, width, 3), 20, dtype=np.uint8), time.perf_counter())


class FakeOverlay(QObject):
    target_lost = Signal()
    instances: list[FakeOverlay] = []

    def __init__(self, hwnd: int, font_family: str = "Segoe UI", **_kwargs) -> None:
        super().__init__()
        self.hwnd = hwnd
        self.font_family = font_family
        self.blocks: list = []
        self.started = self.closed = False
        self.target_rect = FRAME
        FakeOverlay.instances.append(self)

    def start(self) -> None:
        self.started = True

    def apply(self, font_family: str, hide_when_unfocused: bool, exclude_from_capture: bool) -> None:
        self.font_family = font_family

    def close(self) -> None:
        self.closed = True

    @Slot(list)
    def set_blocks(self, blocks: list) -> None:
        self.blocks = list(blocks)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    FakeEngine.created.clear()
    FakeEngine.delay = 0.0
    FakeCapture.fail = FakeCapture.close = False
    FakeCapture.size = (FRAME[2], FRAME[3])
    FakeOverlay.instances.clear()
    info = WindowInfo(HWND, TITLE, "FakeClass", FRAME)

    def find_window(needle: str) -> WindowInfo | None:
        return info if needle.casefold() in TITLE.casefold() else None

    # No key from the environment or an SDK config on the test machine.
    for name in ("DEEPL_AUTH_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(controller_module, "find_window", find_window)
    monkeypatch.setattr(controller_module, "is_window", lambda hwnd: hwnd == HWND)  # the game's window only
    monkeypatch.setattr(controller_module, "window_title", lambda hwnd: TITLE)
    monkeypatch.setattr(controller_module, "capture_area", lambda hwnd, include_frame: (FRAME, CLIENT))
    monkeypatch.setattr(controller_module, "RapidOcrEngine", FakeEngine)
    monkeypatch.setattr(controller_module, "OverlayWindow", FakeOverlay)
    monkeypatch.setattr(pipeline_module, "WgcWindowCapture", FakeCapture)
    yield


@pytest.fixture
def controller(qapp: QApplication, fakes, tmp_path) -> OverlayController:
    c = OverlayController(ProfileStore(tmp_path), MemorySecretStore())
    c.messages: list[str] = []  # type: ignore[attr-defined]
    c.status.connect(c.messages.append)  # type: ignore[attr-defined]
    c.running_log: list[bool] = []  # type: ignore[attr-defined]
    c.running_changed.connect(c.running_log.append)  # type: ignore[attr-defined]
    c.starting_log: list[bool] = []  # type: ignore[attr-defined]
    c.starting_changed.connect(c.starting_log.append)  # type: ignore[attr-defined]
    c.failures: list[str] = []  # type: ignore[attr-defined]
    c.start_failed.connect(c.failures.append)  # type: ignore[attr-defined]
    yield c
    c.close()  # also waits for a start still on its thread, as quitting the app does
    qapp.processEvents()


def settings(**overrides) -> Settings:
    # The whole window: the fake engine answers in crop coordinates, and these tests are about the lifecycle.
    base = {"window_match": "Fake Game", "translator": "uppercase", "use_cache_file": False, "lang": "en", "roi": ""}
    return Settings(**{**base, **overrides})


def test_start_runs_on_a_thread_then_translations_reach_the_overlay(qapp, controller) -> None:
    controller.start(settings())
    assert controller.starting and not controller.running  # the slow part is still on its thread
    wait_for(qapp, lambda: controller.running)
    assert not controller.starting
    assert controller.hwnd == HWND and controller.title == TITLE
    assert controller.running_log == [True]
    assert controller.starting_log == [True, False]
    assert controller.worker is not None and controller.worker.cfg.change_threshold == 20.0
    assert controller.service is not None and controller.service.autosave_seconds == 10.0
    assert any(m.startswith("running on 'Fake Game'") for m in controller.messages)
    assert len(FakeEngine.created) == 1

    (overlay,) = FakeOverlay.instances
    assert overlay.started
    wait_for(qapp, lambda: bool(overlay.blocks))
    assert overlay.blocks[0].lines == ["STAY CLOSE."]

    controller.stop()
    assert not controller.running and overlay.closed
    assert controller.running_log == [True, False]
    assert controller.worker is None and controller.service is None


def test_area_selection_reaches_the_running_pipeline(qapp, controller) -> None:
    controller.start(settings())
    wait_for(qapp, lambda: controller.running)
    worker = controller.worker
    specs: list[str] = []
    controller.area_selected.connect(specs.append)

    controller._selection = (HWND, FRAME, CLIENT)  # as select_area() leaves it
    controller._apply_selected_area((100, 480, 700, 580))  # frame pixels; client area starts 30 px down
    assert specs == ["0.1250,0.7895,0.7500,0.1754"]
    assert controller.settings is not None and controller.settings.roi == specs[0]
    wait_for(qapp, lambda: worker.cfg.roi == (100, 480, 700, 580))  # taken up on the pipeline thread
    assert controller.worker is worker and controller.running_log == [True]  # no restart


def test_edits_apply_at_once_or_restart_the_session(qapp, controller) -> None:
    controller.start(settings())
    wait_for(qapp, lambda: controller.running)
    worker, (overlay,) = controller.worker, FakeOverlay.instances

    controller.apply(settings(font="Arial", subtitle_weight="bold", hide_when_unfocused=False))
    wait_for(qapp, lambda: worker.cfg.subtitle_weight == "bold")
    assert overlay.font_family == "Arial" and controller.worker is worker
    assert controller.settings is not None and controller.settings.font == "Arial"

    controller.apply(settings(font="Arial", subtitle_weight="bold", target_lang="de"))  # a new session is needed
    wait_for(qapp, lambda: controller.running and controller.worker is not worker)
    assert "settings changed: restarting" in controller.messages
    assert controller.settings.target_lang == "de" and controller.worker.cfg.subtitle_weight == "bold"
    assert len(FakeEngine.created) == 1 and len(FakeOverlay.instances) == 2
    assert controller.running_log == [True, False, True]


def test_pipeline_death_ends_the_session(qapp, controller) -> None:
    controller.start(settings())
    wait_for(qapp, lambda: controller.running)
    FakeCapture.fail = True
    wait_for(qapp, lambda: not controller.running)
    assert any(m.startswith("pipeline error: RuntimeError: capture exploded") for m in controller.messages)
    assert "pipeline stopped" in controller.messages
    assert controller.running_log == [True, False]


def test_closed_capture_ends_the_session(qapp, controller) -> None:
    controller.start(settings())
    wait_for(qapp, lambda: controller.running)
    FakeCapture.close = True
    wait_for(qapp, lambda: not controller.running)
    assert "capture closed: target window gone" in controller.messages


def test_start_failures_are_reported_not_raised(qapp, controller) -> None:
    controller.start(settings(window_match="Other Game"))
    wait_for(qapp, lambda: controller.failures)
    assert controller.failures == ["no visible window matching 'Other Game'"]
    assert not controller.running and not controller.starting
    assert controller.starting_log == [True, False]

    controller.failures.clear()
    controller.start(settings(ignore_patterns=["(unclosed"]))
    wait_for(qapp, lambda: controller.failures)
    assert controller.failures[0].startswith("invalid ignore pattern:")

    controller.failures.clear()
    controller.start(settings(translator="dee"))  # half a name never falls through to another translator
    wait_for(qapp, lambda: controller.failures)
    assert controller.failures == ["unknown translator 'dee'"]
    assert FakeOverlay.instances == []


def test_a_missing_key_is_reported_before_waiting_for_the_window(qapp, controller) -> None:
    began = time.monotonic()
    controller.start(settings(window_match="Not Open Yet", translator="deepl"), wait=5.0)
    wait_for(qapp, lambda: controller.failures, timeout=2.0)
    assert controller.failures == ["Add your DeepL key on the Translation page"]
    assert time.monotonic() - began < 2.0  # not after the five seconds the window was waited for

    controller.failures.clear()
    controller.start(settings(draft="deepl"))  # the draft needs the key as much
    wait_for(qapp, lambda: controller.failures)
    assert controller.failures == ["Add your DeepL key on the Translation page"]

    controller.failures.clear()
    controller.start(settings(translator=" Claude "))  # read as "claude", so its key is checked
    wait_for(qapp, lambda: controller.failures)
    assert controller.failures == ["Add your Anthropic key on the Translation page"]
    assert FakeOverlay.instances == []


def test_translators_are_picked_by_name_only(tmp_path: Path) -> None:
    store, secrets = ProfileStore(tmp_path), MemorySecretStore()
    assert isinstance(build_translator(settings(translator=" Uppercase "), "game", store, secrets), UppercaseTranslator)
    for name in ("dee", "Deep L", "", "gpt"):
        with pytest.raises(StartError, match="unknown translator"):
            build_translator(settings(translator=name), "game", store, secrets)


def test_stop_during_start_abandons_the_preparation(qapp, controller) -> None:
    FakeEngine.delay = 0.3
    controller.start(settings())
    assert controller.starting
    controller.stop()
    assert not controller.starting
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert not controller.running and FakeOverlay.instances == []
    assert controller.running_log == [False]  # only stop()'s own notice
    assert controller.starting_log == [True, False]


def test_newer_start_supersedes_an_older_one(qapp, controller) -> None:
    FakeEngine.delay = 0.2
    controller.start(settings(target_lang="de"))
    controller.start(settings(target_lang="tr"))
    wait_for(qapp, lambda: controller.running)
    assert controller.settings is not None and controller.settings.target_lang == "tr"
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert len(FakeOverlay.instances) == 1  # the first preparation's result was dropped
    assert controller.running_log == [True]  # nothing was running to stop: one session began


def test_toggle_cancels_a_start_in_progress(qapp, controller) -> None:
    FakeEngine.delay = 0.3
    controller.toggle(settings())
    assert controller.starting
    controller.toggle(settings())
    assert not controller.starting and not controller.running
    controller.close()  # waits for the abandoned preparation to run out
    assert all(not w.isRunning() for w in controller._start_workers)


def test_a_stale_window_handle_falls_back_to_the_title(qapp, controller) -> None:
    controller.start(settings(), hwnd=0xDEAD)  # picked from a list before the game restarted
    wait_for(qapp, lambda: controller.running)
    assert controller.hwnd == HWND


def test_a_live_handle_is_kept_when_the_window_title_changes(qapp, controller, monkeypatch: pytest.MonkeyPatch) -> None:
    controller.start(settings(), hwnd=HWND)
    wait_for(qapp, lambda: controller.running)
    worker = controller.worker
    # An emulator or a game that shows its frame rate or the level's name in the title.
    monkeypatch.setattr(controller_module, "window_title", lambda hwnd: "Emu | FPS 59")
    monkeypatch.setattr(controller_module, "find_window", lambda needle: None)
    controller.apply(settings(target_lang="de"))  # a restart on the same window
    wait_for(qapp, lambda: controller.failures or (controller.running and controller.worker is not worker))
    assert controller.failures == []
    assert controller.hwnd == HWND and controller.title == "Emu | FPS 59"


def test_an_edit_during_a_start_naming_another_window_drops_the_handle(qapp, controller) -> None:
    FakeEngine.delay = 0.3
    controller.start(settings(), hwnd=HWND)
    controller.apply(settings(window_match="Other Game"))  # picked while the model loads
    wait_for(qapp, lambda: controller.failures or controller.running)
    assert controller.failures == ["no visible window matching 'Other Game'"]
    assert not controller.running


def test_claude_options_do_not_restart_a_session_without_claude(qapp, controller) -> None:
    controller.start(settings())
    wait_for(qapp, lambda: controller.running)
    worker = controller.worker
    controller.apply(settings(model="claude-opus-5-5", tone="formal", effort="high"))
    assert controller.worker is worker and "settings changed: restarting" not in controller.messages
    assert controller.settings is not None and controller.settings.model == "claude-opus-5-5"  # kept for later

    assert restart_fields(settings(translator="claude")) == SESSION_FIELDS
    assert restart_fields(settings(translator="deepl")) == SESSION_FIELDS - CLAUDE_FIELDS


def test_the_cache_is_read_on_the_start_thread(qapp, controller, monkeypatch: pytest.MonkeyPatch) -> None:
    path = controller.store.cache_path(TITLE, "tr", "uppercase")
    stored = TranslationCache(path)
    stored.put("Stay close.", "tr", "Yakın dur.")
    stored.save()
    threads: list[threading.Thread] = []

    def recording_cache(cache_path):
        threads.append(threading.current_thread())
        return TranslationCache(cache_path)

    monkeypatch.setattr(controller_module, "TranslationCache", recording_cache)
    controller.start(settings(use_cache_file=True))
    wait_for(qapp, lambda: controller.running)
    assert threads and threads[0] is not threading.main_thread()  # the UI thread never parses the file
    assert controller.cache is not None and controller.cache.get("Stay close.", "tr") == "Yakın dur."


def test_the_area_follows_a_resized_window(qapp, controller, monkeypatch: pytest.MonkeyPatch) -> None:
    controller.start(settings(roi="0,0.75,1,0.25"))
    wait_for(qapp, lambda: controller.running)
    worker = controller.worker
    assert worker.cfg.frame_size == (800, 600)

    frame, client = (0, 0, 1280, 750), (0, 30, 1280, 750)  # the game went to a larger resolution
    monkeypatch.setattr(controller_module, "capture_area", lambda hwnd, include_frame: (frame, client))
    FakeCapture.size = (1280, 750)
    expected = pipeline_config(controller.settings, frame, client)
    wait_for(qapp, lambda: worker.cfg.frame_size == (1280, 750))
    assert worker.cfg.roi == expected.roi and worker.cfg.area == client
    assert controller.worker is worker  # taken up on the fly, no restart


def test_stop_keeps_the_session_stats_and_a_second_stop_does_nothing(qapp, controller) -> None:
    controller.start(settings())
    wait_for(qapp, lambda: controller.running)
    wait_for(qapp, lambda: bool(FakeOverlay.instances[0].blocks))
    controller.stop()
    assert controller.last_stats.startswith("frames ") and "translation:" in controller.last_stats
    messages, running_log = list(controller.messages), list(controller.running_log)
    controller.stop()  # idle: no second "stopped", no notices
    controller.close()
    assert controller.messages == messages and controller.running_log == running_log


def test_finished_start_threads_are_let_go(qapp, controller) -> None:
    threads = []
    for lang in ("de", "tr", "fr"):
        controller.start(settings(target_lang=lang))
        threads += [weakref.ref(worker) for worker in controller._start_workers]
        wait_for(qapp, lambda lang=lang: controller.running and controller.settings.target_lang == lang)
    wait_for(qapp, lambda: not controller._start_workers)
    assert all(ref() is None for ref in threads)  # nothing keeps a finished start's thread object
