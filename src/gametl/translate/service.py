"""Asynchronous translation front for the pipeline.

The pipeline thread never waits on a translator. Each frame it asks
`lookup_best()` for every stable block that has no final translation yet
and hands the misses to `submit()`, which sends them as one batch on a
worker thread. `drain()` folds finished batches into the cache and the
context window; failed items get a cooldown so a broken network does not
spam requests.

Two tiers: the final translator (Claude) whose results are cached and kept,
and an optional draft translator (offline model) whose results are shown at
once and replaced when the final answer arrives.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from .base import TranslationRequest, Translator
from .cache import TranslationCache, numeric_template

Result = tuple[str, list[str], list[str | None], Exception | None, float]  # kind, texts, results, error, ms


class TranslationService:
    def __init__(
        self,
        translator: Translator,
        cache: TranslationCache | None = None,
        target_lang: str = "tr",
        source_lang: str | None = None,
        workers: int = 2,
        context_lines: int = 10,
        retry_cooldown: float = 3.0,
        on_status: Callable[[str], None] | None = None,
        draft_translator: Translator | None = None,
    ) -> None:
        self.translator = translator
        self.draft_translator = draft_translator
        # Not `cache or ...`: an empty cache has len 0 and would be replaced.
        self.cache = cache if cache is not None else TranslationCache()
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.retry_cooldown = retry_cooldown
        self.on_status = on_status

        self._pool = ThreadPoolExecutor(max_workers=workers + (1 if draft_translator else 0), thread_name_prefix="translate")
        self._lock = threading.Lock()
        self._inflight: set[str] = set()
        self._inflight_templates: set[str] = set()  # numeric templates of in-flight texts
        self._failed_until: dict[str, float] = {}
        self._drafts: dict[str, str] = {}  # key -> draft translation (memory only)
        self._draft_inflight: set[str] = set()
        self._context: deque[tuple[str, str]] = deque(maxlen=context_lines)
        self._futures: list[Future] = []
        self.stats = {"requests": 0, "items": 0, "translated": 0, "errors": 0, "cache_hits": 0, "drafts": 0}
        self.latencies_ms: list[float] = []
        self.draft_latencies_ms: list[float] = []

    # -- pipeline side ---------------------------------------------------------

    def lookup(self, text: str) -> str | None:
        """Final translation from the cache, or None."""
        key = self.cache.key(text)
        with self._lock:
            if key in self._inflight:
                return None
        hit = self.cache.get(text, self.target_lang)
        if hit is not None:
            self.stats["cache_hits"] += 1
        return hit

    def lookup_best(self, text: str) -> tuple[str, bool] | None:
        """(translation, is_final): the cached final translation, else a
        draft if one has arrived, else None."""
        final = self.lookup(text)
        if final is not None:
            return final, True
        with self._lock:
            draft = self._drafts.get(self.cache.key(text))
        return (draft, False) if draft is not None else None

    def submit(self, texts: list[str]) -> bool:
        """Queue one final batch (and one draft batch when a draft translator
        exists) for the texts not already in flight or cooling down. Returns
        True when any request was started."""
        now = time.monotonic()
        batch: list[str] = []
        draft_batch: list[str] = []
        with self._lock:
            seen: set[str] = set()
            for text in texts:
                key = self.cache.key(text)
                if not key or key in seen:
                    continue
                seen.add(key)
                if (
                    self.draft_translator is not None
                    and key not in self._drafts
                    and key not in self._draft_inflight
                ):
                    self._draft_inflight.add(key)
                    draft_batch.append(text)
                if key in self._inflight or self._failed_until.get(key, 0.0) > now:
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
            started = False
            if draft_batch:
                self._futures.append(self._pool.submit(self._run, "draft", draft_batch, []))
                started = True
            if batch:
                context = list(self._context)
                self.stats["requests"] += 1
                self.stats["items"] += len(batch)
                self._futures.append(self._pool.submit(self._run, "final", batch, context))
                started = True
        return started

    def drain(self) -> int:
        """Fold finished batches into the cache. Returns final items translated."""
        with self._lock:
            done = [f for f in self._futures if f.done()]
            self._futures = [f for f in self._futures if not f.done()]
        translated = 0
        for future in done:
            kind, texts, results, error, elapsed_ms = future.result()
            now = time.monotonic()
            if kind == "draft":
                with self._lock:
                    for text, result in zip(texts, results):
                        key = self.cache.key(text)
                        self._draft_inflight.discard(key)
                        if result:
                            self._drafts[key] = result
                            self.stats["drafts"] += 1
                    if error is None:
                        self.draft_latencies_ms.append(elapsed_ms)
                if error is not None and self.on_status:
                    self.on_status(f"draft translation failed ({len(texts)} items): {error}")
                continue

            if error is None:
                self.latencies_ms.append(elapsed_ms)
                if self.on_status:
                    self.on_status(f"translated {len(texts)} item(s) in {elapsed_ms:.0f} ms")
            with self._lock:
                for text, result in zip(texts, results):
                    key = self.cache.key(text)
                    self._inflight.discard(key)
                    self._inflight_templates.discard(numeric_template(key)[0])
                    if result:
                        self.cache.put(text, self.target_lang, result)
                        self._context.append((text, result))
                        self._drafts.pop(key, None)
                        translated += 1
                    else:
                        self._failed_until[key] = now + self.retry_cooldown
            if error is not None:
                self.stats["errors"] += 1
                if self.on_status:
                    self.on_status(f"translation failed ({len(texts)} items): {error}")
        self.stats["translated"] += translated
        return translated

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._inflight)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.cache.save()

    # -- worker side -----------------------------------------------------------

    def _run(self, kind: str, texts: list[str], context: list[tuple[str, str]]) -> Result:
        translator = self.draft_translator if kind == "draft" else self.translator
        assert translator is not None
        request = TranslationRequest(
            texts=texts, source_lang=self.source_lang, target_lang=self.target_lang, context=context
        )
        t0 = time.perf_counter()
        try:
            results = translator.translate(request)
        except Exception as exc:  # any backend failure: cool down the whole batch
            return kind, texts, [None] * len(texts), exc, (time.perf_counter() - t0) * 1000
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if len(results) != len(texts):
            return kind, texts, [None] * len(texts), RuntimeError("translator returned a wrong number of items"), elapsed_ms
        return kind, texts, results, None, elapsed_ms
