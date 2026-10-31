"""Asynchronous translation front for the pipeline.

The pipeline thread never waits on a translator. Each frame it asks
`lookup_best()` for every stable block without a final translation and
hands the misses to `submit()`, which sends the ones the cache cannot
answer as one batch on a worker thread. `drain()` folds finished batches
into the cache and the context window. A failed request holds back its tier
for a cooldown, and an item that came back empty waits on its own, so a
broken network or a rejected key does not spam requests.

Two tiers: the final translator, whose results are cached and kept, and an
optional draft translator (offline model or DeepL) whose results are shown
at once and replaced when the final answer arrives.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from .base import TranslationRequest, Translator
from .cache import TranslationCache, numeric_template


@dataclass(slots=True)
class BatchResult:
    kind: str  # "final" | "draft"
    texts: list[str]
    results: list[str | None]  # one per text; None = not translated
    error: Exception | None
    elapsed_ms: float


def _said_by(speaker: str, text: str) -> str:
    """A line as the context shows it: with its speaker in front, when one was named."""
    return f"{speaker}: {text}" if speaker else text


def _unexpired(until: dict[str, float], now: float) -> dict[str, float]:
    """The cooldowns in `until` (key -> monotonic time) that have not passed."""
    return {key: t for key, t in until.items() if t > now} if until else until


class _DaemonPool:
    """A fixed set of daemon worker threads behind `Future`s. Unlike
    ThreadPoolExecutor's workers, daemon threads do not hold the process
    open at exit: a translation request still waiting on the network when
    the user quits ends with the process instead of delaying it by the
    HTTP timeout."""

    def __init__(self, workers: int, name: str) -> None:
        self._queue: queue.SimpleQueue[tuple[Future, Callable[..., Any], tuple[Any, ...]] | None] = queue.SimpleQueue()
        self._threads = [
            threading.Thread(target=self._loop, name=f"{name}-{i}", daemon=True) for i in range(max(1, workers))
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future:
        future: Future = Future()
        self._queue.put((future, fn, args))
        return future

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, fn, args = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args))
            except BaseException as exc:  # the future carries it to drain()
                future.set_exception(exc)

    def shutdown(self) -> None:
        """Let each worker finish its current item and exit; queued items
        after that are dropped."""
        for _ in self._threads:
            self._queue.put(None)


class TranslationService:
    def __init__(
        self,
        translator: Translator,
        cache: TranslationCache | None = None,
        target_lang: str = "tr",
        source_lang: str | None = None,
        workers: int = 2,
        context_lines: int = 30,  # recent (source, translation) pairs handed to the translator as context
        retry_cooldown: float = 3.0,
        on_status: Callable[[str], None] | None = None,
        draft_translator: Translator | None = None,
        autosave_seconds: float = 10.0,
        max_drafts: int = 500,
    ) -> None:
        self.translator = translator
        self.draft_translator = draft_translator
        # Not `cache or ...`: an empty cache has len 0 and would be replaced.
        self.cache = cache if cache is not None else TranslationCache()
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.context_lines = context_lines
        self.retry_cooldown = retry_cooldown
        self.on_status = on_status
        # New translations reach the disk at most this long after arriving, so
        # a crash or a killed process loses at most this much work.
        self.autosave_seconds = autosave_seconds
        self.max_drafts = max_drafts

        workers += 1 if draft_translator else 0
        self._pool = _DaemonPool(workers, "translate")
        self._lock = threading.Lock()
        # Final tier. A failed request holds back the whole tier for a while
        # (`_backoff_until`): per-text cooldowns would not stop a ticking
        # counter, whose every tick is a new text. An item that came back
        # empty from a request that worked waits on its own (`_failed_until`).
        self._inflight: set[str] = set()
        self._inflight_templates: set[str] = set()  # numeric templates of in-flight texts
        self._failed_until: dict[str, float] = {}
        self._backoff_until = 0.0
        # Draft tier, the same way.
        self._drafts: dict[str, str] = {}  # key -> draft translation (memory only, oldest first)
        self._draft_inflight: set[str] = set()
        self._draft_failed_until: dict[str, float] = {}
        self._draft_backoff_until = 0.0
        self._last_save = time.monotonic()
        # The lines of the scene, each once: key -> (source, translation), oldest first. The source
        # carries its speaker ("Casey: Go.") so the translator sees who said what; the texts sent
        # never do (see `speakers` in submit).
        self._context: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._speakers: dict[str, str] = {}  # key -> who says it, for the texts in flight
        self._arrived: set[str] = set()  # keys whose final answer just came in: their next lookup is no cache hit
        self._futures: list[Future[BatchResult]] = []
        self.stats = {"requests": 0, "items": 0, "translated": 0, "errors": 0, "cache_hits": 0, "drafts": 0}
        self.latencies_ms: deque[float] = deque(maxlen=5000)
        self.draft_latencies_ms: deque[float] = deque(maxlen=5000)

    # -- pipeline side ---------------------------------------------------------

    def lookup(self, text: str, speaker: str = "") -> str | None:
        """The final translation from the cache, or None."""
        key = self.cache.key(text)
        with self._lock:
            if key in self._inflight:
                return None
        hit = self.cache.get(text, self.target_lang)
        if hit is not None:
            with self._lock:
                if key in self._arrived:  # its own answer, just in: that is no cache hit
                    self._arrived.discard(key)
                else:
                    self.stats["cache_hits"] += 1
                self._remember(key, _said_by(speaker, text), hit)  # a line shown from the cache is in the scene too
        return hit

    def lookup_best(self, text: str, speaker: str = "") -> tuple[str, bool] | None:
        """(translation, is_final): the cached final translation, else a
        draft if one has arrived, else None."""
        final = self.lookup(text, speaker)
        if final is not None:
            return final, True
        with self._lock:
            draft = self._drafts.get(self.cache.key(text))
        return (draft, False) if draft is not None else None

    def submit(self, texts: list[str], speakers: list[str] | None = None) -> bool:
        """Queue one final batch (and one draft batch when a draft translator
        exists) for the texts the cache cannot answer and that are not
        already in flight or cooling down. `speakers`, one per text, names
        who says each ("" = nobody named): it goes along as a hint and into
        the context, never into the text. Returns True when any request was
        started."""
        todo: dict[str, str] = {}  # key -> text: each text once
        said: dict[str, str] = {}  # key -> speaker, where one is named
        for i, text in enumerate(texts):
            key = self.cache.key(text)
            todo.setdefault(key, text)
            if speakers and speakers[i]:
                said[key] = speakers[i]
        todo.pop("", None)
        # What the cache answers (exactly, by number swap or fuzzily) lookup()
        # shows at once; a request would only spend characters, delay the line
        # and overwrite the cached translation.
        todo = {key: text for key, text in todo.items() if self.cache.get(text, self.target_lang) is None}

        now = time.monotonic()
        batch: list[str] = []
        draft_batch: list[str] = []
        with self._lock:
            self._speakers.update(said)
            # Cooldowns that have passed are of no further use.
            self._failed_until = _unexpired(self._failed_until, now)
            self._draft_failed_until = _unexpired(self._draft_failed_until, now)
            # Per text: does it need a draft request, a final request, both, or neither?
            for key, text in todo.items():
                if self._draft_due(key, now):
                    self._draft_inflight.add(key)
                    draft_batch.append(text)
                if not self._final_due(key, now):
                    continue
                # A ticking counter: the same text with other numbers is already
                # on its way; its answer will serve this one by number swap.
                template, numbers = numeric_template(key)
                if numbers and template in self._inflight_templates:
                    continue
                self._inflight.add(key)
                if numbers:
                    self._inflight_templates.add(template)
                batch.append(text)
            # One request per tier. The draft goes without context: speed over consistency.
            if draft_batch:
                self._futures.append(self._pool.submit(self._run, "draft", draft_batch, [], self._said(draft_batch)))
            if batch:
                self.stats["requests"] += 1
                self.stats["items"] += len(batch)
                context = list(self._context.values())
                self._futures.append(self._pool.submit(self._run, "final", batch, context, self._said(batch)))
        return bool(draft_batch or batch)

    def _said(self, texts: list[str]) -> list[str] | None:
        """Who says each of `texts`, or None when nobody is named. Call with the lock held."""
        speakers = [self._speakers.get(self.cache.key(text), "") for text in texts]
        return speakers if any(speakers) else None

    def _final_due(self, key: str, now: float) -> bool:
        """Whether a final request for `key` may start now. Call with the lock held."""
        return now >= self._backoff_until and key not in self._inflight and self._failed_until.get(key, 0.0) <= now

    def _draft_due(self, key: str, now: float) -> bool:
        """Whether a draft request for `key` may start now. Call with the lock held."""
        return (
            self.draft_translator is not None
            and now >= self._draft_backoff_until
            and key not in self._drafts
            and key not in self._draft_inflight
            and self._draft_failed_until.get(key, 0.0) <= now
        )

    def _remember(self, key: str, text: str, translation: str) -> None:
        """Put a line at the new end of the context, once however often it is
        seen, dropping the oldest beyond `context_lines`. Call with the lock held."""
        self._context[key] = (text, translation)
        self._context.move_to_end(key)
        while len(self._context) > self.context_lines:
            oldest, _ = self._context.popitem(last=False)
            self._arrived.discard(oldest)

    def drain(self) -> int:
        """Fold finished batches into the cache. Returns the number of final
        translations that arrived."""
        with self._lock:
            # One pass: a future finishing between two passes would be in neither list.
            done, pending = [], []
            for future in self._futures:
                (done if future.done() else pending).append(future)
            self._futures = pending
        translated = 0
        for future in done:
            batch = future.result()
            if batch.kind == "draft":
                self._absorb_draft(batch)
            else:
                translated += self._absorb_final(batch)
        self.stats["translated"] += translated
        # On every call, not only when something arrived: a translation that
        # came in just after a save must not wait for the next one to reach the disk.
        self._autosave()
        return translated

    def _autosave(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_save >= self.autosave_seconds:
            try:
                self.cache.save()  # returns at once when nothing changed
            except OSError as exc:
                self._report(f"could not save the translation cache: {exc}")
            self._last_save = now

    def _absorb_draft(self, batch: BatchResult) -> None:
        now = time.monotonic()
        with self._lock:
            for text, result in zip(batch.texts, batch.results, strict=True):
                key = self.cache.key(text)
                self._draft_inflight.discard(key)
                if not result:
                    if batch.error is None:  # this item only; a failed request holds back the tier below
                        self._draft_failed_until[key] = now + self.retry_cooldown
                    continue
                if self.cache.get(text, self.target_lang) is not None:
                    continue  # the final answer overtook the draft: no use keeping it
                self._drafts[key] = result
                self.stats["drafts"] += 1
                while len(self._drafts) > self.max_drafts:  # bounded: a long session must not grow memory
                    self._drafts.pop(next(iter(self._drafts)))
            if batch.error is None:
                self.draft_latencies_ms.append(batch.elapsed_ms)
            else:
                self._draft_backoff_until = now + self._backoff_for(batch.error)
        if batch.error is not None:
            self._report(f"draft translation failed ({len(batch.texts)} items): {batch.error}")

    def _absorb_final(self, batch: BatchResult) -> int:
        translated = 0
        now = time.monotonic()
        with self._lock:
            for text, result in zip(batch.texts, batch.results, strict=True):
                key = self.cache.key(text)
                self._inflight.discard(key)
                self._inflight_templates.discard(numeric_template(key)[0])
                speaker = self._speakers.pop(key, "")  # a retry names the speaker again
                if result:
                    self.cache.put(text, self.target_lang, result)
                    self._drafts.pop(key, None)
                    self._arrived.add(key)
                    self._remember(key, _said_by(speaker, text), result)
                    translated += 1
                elif batch.error is None:  # this item only; a failed request holds back the tier below
                    self._failed_until[key] = now + self.retry_cooldown
            if batch.error is None:
                self.latencies_ms.append(batch.elapsed_ms)
            else:
                self._backoff_until = now + self._backoff_for(batch.error)
        if batch.error is None:
            self._log(f"translated {len(batch.texts)} item(s) in {batch.elapsed_ms:.0f} ms")
        else:
            self.stats["errors"] += 1
            self._report(f"translation failed ({len(batch.texts)} items): {batch.error}")
        return translated

    def _backoff_for(self, error: Exception) -> float:
        """Seconds a tier waits after a failed request: the usual cooldown, or
        longer when the backend asked for it (a rejected key, a used-up quota)."""
        return max(self.retry_cooldown, getattr(error, "retry_after", 0.0))

    def _report(self, text: str) -> None:
        """To the status line: what the player may need to act on."""
        if self.on_status:
            self.on_status(text)

    @staticmethod
    def _log(text: str) -> None:
        """To the log only: routine timings would crowd the status line."""
        print(text, flush=True)

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._inflight)

    def shutdown(self) -> None:
        """Fold in what has already arrived, stop the workers and save the cache."""
        self.drain()  # answers that came in after the last frame would otherwise be asked for again next session
        self._pool.shutdown()
        self._autosave(force=True)

    # -- worker side -----------------------------------------------------------

    def _run(
        self, kind: str, texts: list[str], context: list[tuple[str, str]], speakers: list[str] | None
    ) -> BatchResult:
        translator = self.draft_translator if kind == "draft" else self.translator
        assert translator is not None
        request = TranslationRequest(
            texts=texts, source_lang=self.source_lang, target_lang=self.target_lang, context=context, speakers=speakers
        )
        t0 = time.perf_counter()
        results: list[str | None] = [None] * len(texts)
        error: Exception | None = None
        try:
            got = translator.translate(request)
        except Exception as exc:  # any backend failure cools down the whole batch
            error = exc
        else:
            if len(got) == len(texts):
                results = list(got)
            else:
                error = RuntimeError(f"translator returned {len(got)} items for {len(texts)} texts")
        return BatchResult(kind, texts, results, error, (time.perf_counter() - t0) * 1000)
