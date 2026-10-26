"""OverlayController lifecycle with fakes for the window, the capture, the
OCR engine and the overlay: start on a thread, stop, restart on an area
selection, a pipeline that dies, and starts that cannot go ahead."""

from __future__ import annotations

import os
import time
from datetime import date, timedelta

import numpy as np
import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication

from gametl.app import controller as controller_module
from gametl.app import pipeline as pipeline_module
from gametl.app.config import ProfileStore, Settings
from gametl.app.controller import OverlayController
from gametl.app.credentials import MemorySecretStore
from gametl.capture.base import Frame
from gametl.capture.windows import WindowInfo
from gametl.ocr.base import OcrResult, TextLine
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
    pipeline thread die, `closed` ends it as a closed window would."""

    fail = False
    close = False

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
        return Frame(np.full((600, 800, 3), 20, dtype=np.uint8), time.perf_counter())


class FakeOverlay(QObject):
    target_lost = Signal()
    instances: list[FakeOverlay] = []

    def __init__(self, hwnd: int, **_kwargs) -> None:
        super().__init__()
        self.hwnd = hwnd
        self.blocks: list = []
        self.started = self.closed = False
        self.target_rect = FRAME
        FakeOverlay.instances.append(self)

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    @Slot(list)
    def set_blocks(self, blocks: list) -> None:
        self.blocks = list(blocks)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch):
    FakeEngine.created.clear()
    FakeEngine.delay = 0.0
    FakeCapture.fail = FakeCapture.close = False
    FakeOverlay.instances.clear()
    info = WindowInfo(HWND, TITLE, "FakeClass", FRAME)

    def find_window(needle: str) -> WindowInfo | None:
        return info if needle.casefold() in TITLE.casefold() else None

    monkeypatch.setattr(controller_module, "find_window", find_window)
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
    base = {"window_match": "Fake Game", "translator": "uppercase", "use_cache_file": False, "lang": "en"}
    return Settings(**{**base, **overrides})


def test_start_runs_on_a_thread_then_translations_reach_the_overlay(qapp, controller) -> None:
    assert controller.start(settings()) is True
    assert controller.starting and not controller.running  # the slow part is still on its thread
    wait_for(qapp, lambda: controller.running)
    assert not controller.starting
    assert controller.hwnd == HWND and controller.title == TITLE
    assert controller.running_log == [True]
    assert controller.starting_log == [True, False]
    assert controller.worker is not None and controller.worker.cfg.diff_threshold == 1.0
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


def test_area_selection_restarts_on_the_same_engine(qapp, controller) -> None:
    controller.start(settings())
    wait_for(qapp, lambda: controller.running)
    first_worker = controller.worker
    specs: list[str] = []
    controller.area_selected.connect(specs.append)

    controller._selection = (HWND, FRAME, CLIENT)  # as select_area() leaves it
    controller._apply_selected_area((100, 480, 700, 580))  # frame pixels; client area starts 30 px down
    assert specs == ["0.1250,0.7895,0.7500,0.1754"]
    assert controller.settings is not None and controller.settings.roi == specs[0]
    assert controller.settings.full_scan_every == 0
    wait_for(qapp, lambda: controller.running and controller.worker is not first_worker)
    assert len(FakeEngine.created) == 1  # the loaded engine is reused
    assert controller.worker.cfg.roi == (100, 480, 700, 580)
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
    controller.start(settings(translator="deepl"))  # no key anywhere
    wait_for(qapp, lambda: controller.failures)
    assert controller.failures[0].startswith("translator setup failed: DeepL needs an API key")
    assert FakeOverlay.instances == []


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


def test_trial_over_refuses_to_start(qapp, fakes, tmp_path) -> None:
    secrets = MemorySecretStore()
    secrets.set("TRIAL_START", (date.today() - timedelta(days=60)).isoformat())
    c = OverlayController(ProfileStore(tmp_path), secrets)
    messages: list[str] = []
    c.status.connect(messages.append)
    assert c.start(settings()) is False
    assert messages == ["trial over: a licence key is needed: enter one in Settings > Licence"]
