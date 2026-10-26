from __future__ import annotations

import threading
import time

from gametl.translate.base import TranslationError, TranslationRequest
from gametl.translate.cache import TranslationCache
from gametl.translate.service import TranslationService
from tests.helpers import wait_until


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
        assert sorted(r.texts for r in translator.requests) == [["HP 24   5s"], ["Open the door."]]  # workers race
        assert service.lookup("HP 24 6s") == "HP 24   6S"  # served by number swap
        assert service.lookup("HP 24 7s") == "HP 24   7S"
    finally:
        service.shutdown()


def test_new_translations_are_saved_to_disk_without_a_shutdown(tmp_path) -> None:
    translator = GatedTranslator()
    translator.release.set()
    path = tmp_path / "game.tr.json"
    service = TranslationService(translator, TranslationCache(path), autosave_seconds=0)
    try:
        service.submit(["Stay close."])
        assert wait_until(lambda: service.drain() > 0)
        assert path.exists()  # written by drain(), not by shutdown()
        assert TranslationCache(path).get("Stay close.", "tr") == "STAY CLOSE."
    finally:
        service.shutdown()

    # With a long interval the first result waits for the interval; shutdown still writes it.
    path2 = tmp_path / "other.tr.json"
    service = TranslationService(translator, TranslationCache(path2), autosave_seconds=3600)
    try:
        service.submit(["Run!"])
        assert wait_until(lambda: service.drain() > 0)
        assert not path2.exists()
    finally:
        service.shutdown()
    assert path2.exists()


class InstantDraft:
    name = "draft"

    def translate(self, request: TranslationRequest) -> list[str | None]:
        return [f"draft:{t}" for t in request.texts]


def test_draft_is_shown_first_then_replaced_by_the_final() -> None:
    final = GatedTranslator()
    service = TranslationService(final, draft_translator=InstantDraft())
    try:
        assert service.lookup_best("Stay close.") is None
        assert service.submit(["Stay close."]) is True
        assert wait_until(lambda: (service.drain(), service.lookup_best("Stay close.") is not None)[1])
        assert service.lookup_best("Stay close.") == ("draft:Stay close.", False)
        assert service.stats["drafts"] == 1
        assert service.submit(["Stay close."]) is False  # final in flight, draft present: nothing new

        final.release.set()
        assert wait_until(lambda: service.drain() > 0)
        assert service.lookup_best("Stay close.") == ("STAY CLOSE.", True)
        assert service.lookup("Stay close.") == "STAY CLOSE."
    finally:
        service.shutdown()


def test_drafts_are_bounded_and_dropped_once_the_final_exists() -> None:
    final = GatedTranslator()
    service = TranslationService(final, draft_translator=InstantDraft(), max_drafts=2)
    try:
        service.submit(["one", "two", "three"])
        assert wait_until(lambda: (service.drain(), service.stats["drafts"] == 3)[1])
        assert len(service._drafts) == 2 and "one" not in service._drafts  # oldest dropped
        final.release.set()
        assert wait_until(lambda: service.drain() > 0)
        assert service._drafts == {}  # finals replace every draft
    finally:
        service.shutdown()

    # A draft that arrives after the final is not kept.
    final = GatedTranslator()
    final.release.set()
    draft = GatedTranslator()
    draft.name = "draft"
    service = TranslationService(final, draft_translator=draft)
    try:
        service.submit(["late"])
        assert wait_until(lambda: service.drain() > 0)
        assert service.lookup("late") == "LATE"
        draft.release.set()
        assert wait_until(lambda: (service.drain(), not service._draft_inflight)[1])
        assert service._drafts == {}
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
        assert service.submit(["x"]) is True  # the cooldown that passed is forgotten
        assert wait_until(lambda: service.drain() > 0)
        assert service.lookup("x") == "X"
    finally:
        service.shutdown()
