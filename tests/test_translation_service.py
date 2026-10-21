from __future__ import annotations

import threading
import time

from gametl.translate.base import TranslationError, TranslationRequest
from gametl.translate.cache import TranslationCache
from gametl.translate.service import TranslationService


class GatedTranslator:
    """Upper-cases, but only once `release` is set; records every request."""

    name = "gated"

    def __init__(self) -> None:
        self.release = threading.Event()
        self.requests: list[TranslationRequest] = []
        self.fail = False

    def translate(self, request: TranslationRequest) -> list[str | None]:
        self.requests.append(request)
        assert self.release.wait(5.0)
        if self.fail:
            raise TranslationError("boom")
        return [t.upper() for t in request.texts]


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_submit_batches_and_results_arrive_via_drain() -> None:
    translator = GatedTranslator()
    service = TranslationService(translator, TranslationCache(), target_lang="tr", source_lang="en")
    try:
        assert service.lookup("Stay close.") is None
        assert service.submit(["Stay close.", "Open the door.", "stay close."]) is True  # dedup within batch
        assert service.submit(["Stay close."]) is False  # already in flight
        assert service.pending == 2
        assert service.lookup("Stay close.") is None  # in flight: no fuzzy scan, no hit

        translator.release.set()
        assert wait_until(lambda: service.drain() > 0)
        assert service.pending == 0
        assert service.lookup("Stay close.") == "STAY CLOSE."
        assert service.lookup("Open the door.") == "OPEN THE DOOR."

        (request,) = translator.requests
        assert request.texts == ["Stay close.", "Open the door."]
        assert request.source_lang == "en" and request.target_lang == "tr"
        assert service.stats["requests"] == 1 and service.stats["translated"] == 2
    finally:
        service.shutdown()


def test_ticking_counter_waits_for_the_in_flight_sibling() -> None:
    translator = GatedTranslator()
    service = TranslationService(translator)
    try:
        assert service.submit(["HP 24   5s"]) is True
        assert service.submit(["HP 24   6s"]) is False  # same template in flight: no second request
        assert service.submit(["HP 24   7s", "Open the door."]) is True  # only the new text goes
        translator.release.set()
        assert wait_until(lambda: service.drain() > 0 and service.pending == 0)
        assert [r.texts for r in translator.requests] == [["HP 24   5s"], ["Open the door."]]
        assert service.lookup("HP 24 6s") == "HP 24   6S"  # served by number swap
        assert service.lookup("HP 24 7s") == "HP 24   7S"
    finally:
        service.shutdown()


def test_context_carries_recent_pairs() -> None:
    translator = GatedTranslator()
    translator.release.set()
    service = TranslationService(translator, context_lines=2)
    try:
        service.submit(["one"])
        assert wait_until(lambda: service.drain() > 0)
        service.submit(["two"])
        assert wait_until(lambda: service.drain() > 0)
        service.submit(["three"])
        assert wait_until(lambda: service.drain() > 0)
        assert translator.requests[1].context == [("one", "ONE")]
        assert translator.requests[2].context == [("one", "ONE"), ("two", "TWO")]
    finally:
        service.shutdown()


def test_failed_batch_cools_down_then_retries() -> None:
    translator = GatedTranslator()
    translator.fail = True
    translator.release.set()
    messages: list[str] = []
    service = TranslationService(translator, retry_cooldown=0.2, on_status=messages.append)
    try:
        service.submit(["x"])
        assert wait_until(lambda: service.drain() >= 0 and service.pending == 0)
        assert service.stats["errors"] == 1
        assert messages and "boom" in messages[0]
        assert service.submit(["x"]) is False  # cooling down
        time.sleep(0.25)
        translator.fail = False
        assert service.submit(["x"]) is True
        assert wait_until(lambda: service.drain() > 0)
        assert service.lookup("x") == "X"
    finally:
        service.shutdown()
