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

    # A translation that arrives just after a save reaches the disk once the
    # interval has passed, even when nothing else arrives after it.
    path_quiet = tmp_path / "quiet.tr.json"
    service = TranslationService(translator, TranslationCache(path_quiet), autosave_seconds=0.3)
    try:
        service.submit(["Hold on."])
        assert wait_until(lambda: service.drain() > 0)
        assert wait_until(lambda: (service.drain(), path_quiet.exists())[1])  # empty drains save it
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
        # A line answered from the cache joins the context as well, once.
        assert service.lookup("two") == "TWO" and service.lookup("two") == "TWO"
        service.submit(["four"])
        assert wait_until(lambda: service.drain() > 0)
        assert translator.requests[3].context == [("three", "THREE"), ("two", "TWO")]
    finally:
        service.shutdown()


def test_speakers_go_along_as_a_hint_and_name_the_context_lines() -> None:
    translator = GatedTranslator()
    translator.release.set()
    service = TranslationService(translator, context_lines=4)
    try:
        service.submit(["Stay close.", "Where?"], ["Casey", ""])
        assert wait_until(lambda: service.drain() > 0)
        assert translator.requests[0].speakers == ["Casey", ""]
        assert translator.requests[0].texts == ["Stay close.", "Where?"]  # the name never enters the text
        service.submit(["Go."])  # nobody named: no speakers at all
        assert wait_until(lambda: service.drain() > 0)
        assert translator.requests[1].speakers is None
        assert translator.requests[1].context == [("Casey: Stay close.", "STAY CLOSE."), ("Where?", "WHERE?")]
        assert service.cache.get("Stay close.", "tr") == "STAY CLOSE."  # cached by the words alone
        assert service.lookup("Go.", "Alan") == "GO."  # a cached line joins the context with its speaker
        assert list(service._context.values())[-1] == ("Alan: Go.", "GO.")
        assert service._speakers == {}  # nothing in flight keeps a name
        service.submit(["Stay close."], ["Casey"])  # answered by the cache: no request, nothing kept
        assert service._speakers == {}
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


def test_cached_texts_are_not_sent_again() -> None:
    """A line the cache answers costs no request: it is shown from the cache,
    and the cached translation is not overwritten by a new answer."""
    translator = GatedTranslator()
    translator.release.set()
    draft = GatedTranslator()
    draft.release.set()
    cache = TranslationCache()
    cache.put("Stay close.", "tr", "Yakın dur.")
    cache.put("HP 24   5s", "tr", "Can 24   5sn")
    service = TranslationService(translator, cache, draft_translator=draft)
    try:
        # Exact, case and spacing, number swap: all answered by the cache, in neither tier.
        assert service.submit(["Stay close.", "stay  close.", "HP 24 6s"]) is False
        assert translator.requests == [] and draft.requests == []
        assert service.lookup_best("Stay close.") == ("Yakın dur.", True)  # not hidden behind a request

        assert service.submit(["Stay close.", "Open the door."]) is True
        assert wait_until(lambda: service.drain() > 0)
        assert [r.texts for r in translator.requests] == [["Open the door."]]
        assert cache.get("Stay close.", "tr") == "Yakın dur."  # untouched
    finally:
        service.shutdown()


class FailingTranslator:
    """Fails every request after counting it."""

    name = "failing"

    def __init__(self, retry_after: float = 0.0) -> None:
        self.requests: list[TranslationRequest] = []
        self.retry_after = retry_after

    def translate(self, request: TranslationRequest) -> list[str | None]:
        self.requests.append(request)
        raise TranslationError("DeepL monthly quota used up", retry_after=self.retry_after)


def test_a_failing_draft_translator_is_asked_once_per_cooldown() -> None:
    final = GatedTranslator()  # slow: the line has no translation for a while
    draft = FailingTranslator()
    messages: list[str] = []
    service = TranslationService(final, draft_translator=draft, retry_cooldown=0.3, on_status=messages.append)
    try:
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:  # the pipeline resubmits a line without a translation every frame
            service.drain()
            service.submit(["Stay close."])
            time.sleep(0.01)
        assert len(draft.requests) == 1 and len(final.requests) == 1
        assert len(messages) == 1 and "draft translation failed" in messages[0]
        time.sleep(0.15)
        service.drain()
        assert service.submit(["Stay close."]) is True  # the cooldown passed: tried again
        assert wait_until(lambda: len(draft.requests) == 2)
    finally:
        final.release.set()
        service.shutdown()


def test_a_failed_request_holds_back_the_whole_tier() -> None:
    """A ticking counter makes a new text each tick; with the network down it
    must not make a request each tick."""
    translator = FailingTranslator()
    service = TranslationService(translator, retry_cooldown=0.3)
    try:
        assert service.submit(["Time left 10"]) is True
        assert wait_until(lambda: (service.drain(), service.pending == 0)[1])
        for seconds in range(9, 0, -1):
            assert service.submit([f"Time left {seconds}", "Open the door."]) is False
        assert len(translator.requests) == 1
        time.sleep(0.35)
        assert service.submit(["Time left 1"]) is True
    finally:
        service.shutdown()

    # A backend that asks for a longer pause (a rejected key, a used-up quota) gets it.
    translator = FailingTranslator(retry_after=60.0)
    service = TranslationService(translator, retry_cooldown=0.1)
    try:
        service.submit(["a"])
        assert wait_until(lambda: (service.drain(), service.pending == 0)[1])
        time.sleep(0.15)
        assert service.submit(["a"]) is False
    finally:
        service.shutdown()


class PartialTranslator:
    """Leaves out the texts named in `skip`."""

    name = "partial"

    def __init__(self, skip: set[str]) -> None:
        self.skip = skip
        self.requests: list[TranslationRequest] = []

    def translate(self, request: TranslationRequest) -> list[str | None]:
        self.requests.append(request)
        return [None if t in self.skip else t.upper() for t in request.texts]


def test_an_item_that_came_back_empty_cools_down_alone() -> None:
    translator = PartialTranslator(skip={"???"})
    service = TranslationService(translator, retry_cooldown=60.0)
    try:
        service.submit(["???", "Run!"])
        assert wait_until(lambda: service.drain() > 0)
        assert service.submit(["???"]) is False  # cooling down
        assert service.submit(["Open the door."]) is True  # the tier itself is not held back
    finally:
        service.shutdown()


def test_each_line_enters_the_context_once_and_fresh_answers_are_no_cache_hits() -> None:
    translator = GatedTranslator()
    translator.release.set()
    service = TranslationService(translator, context_lines=3)
    try:
        service.submit(["A", "B"])
        assert wait_until(lambda: service.drain() > 0)
        assert service.lookup("A") == "A" and service.lookup("B") == "B"  # the pipeline shows the new answers
        assert service.stats["cache_hits"] == 0
        assert list(service._context.values()) == [("A", "A"), ("B", "B")]

        assert service.lookup("A") == "A"  # the line comes back later: from the cache
        assert service.stats["cache_hits"] == 1
        service.submit(["C", "D"])
        assert wait_until(lambda: service.drain() > 0)
        assert translator.requests[1].context == [("B", "B"), ("A", "A")]  # once each, the reused line last
        assert [source for source, _ in service._context.values()] == ["A", "C", "D"]  # the oldest dropped
    finally:
        service.shutdown()


def test_shutdown_keeps_answers_that_arrived_after_the_last_drain(tmp_path) -> None:
    translator = GatedTranslator()
    translator.release.set()
    path = tmp_path / "game.tr.json"
    service = TranslationService(translator, TranslationCache(path), autosave_seconds=3600)
    service.submit(["Stay close."])
    assert wait_until(lambda: all(future.done() for future in service._futures))
    service.shutdown()  # no drain() since the answer came in
    assert TranslationCache(path).get("Stay close.", "tr") == "STAY CLOSE."


def test_timings_go_to_the_log_and_errors_to_the_status_line(capsys) -> None:
    translator = GatedTranslator()
    translator.release.set()
    messages: list[str] = []
    service = TranslationService(translator, on_status=messages.append)
    try:
        service.submit(["Run!"])
        assert wait_until(lambda: service.drain() > 0)
        assert messages == []
        assert "translated 1 item(s)" in capsys.readouterr().out
        translator.fail = True
        service.submit(["Hide!"])
        assert wait_until(lambda: (service.drain(), bool(messages))[1])
        assert "boom" in messages[0]
    finally:
        service.shutdown()
