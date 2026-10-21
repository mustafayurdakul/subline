"""Asynchronous translation front for the pipeline.

The pipeline thread never waits on a translator. Each frame it asks
`lookup()` for every stable, untranslated block (cache, including results
that arrived since the last frame) and hands the misses to `submit()`, which
sends them as one batch on a worker thread. `drain()` folds finished batches
into the cache and the context window; failed items get a cooldown so a
broken network does not spam requests.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from .base import TranslationRequest, Translator
from .cache import TranslationCache


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
    ) -> None:
        self.translator = translator
        # Not `cache or ...`: an empty cache has len 0 and would be replaced.
        self.cache = cache if cache is not None else TranslationCache()
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.retry_cooldown = retry_cooldown
        self.on_status = on_status

        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="translate")
        self._lock = threading.Lock()
        self._inflight: set[str] = set()
        self._failed_until: dict[str, float] = {}
        self._context: deque[tuple[str, str]] = deque(maxlen=context_lines)
        self._futures: list[Future] = []
        self.stats = {"requests": 0, "items": 0, "translated": 0, "errors": 0, "cache_hits": 0}

    # -- pipeline side ---------------------------------------------------------

    def lookup(self, text: str) -> str | None:
        key = self.cache.key(text)
        with self._lock:
            if key in self._inflight:
                return None
        hit = self.cache.get(text, self.target_lang)
        if hit is not None:
            self.stats["cache_hits"] += 1
        return hit

    def submit(self, texts: list[str]) -> bool:
        """Queue one batch for the texts not already in flight or cooling
        down. Returns True when a request was started."""
        now = time.monotonic()
        batch: list[str] = []
        with self._lock:
            seen: set[str] = set()
            for text in texts:
                key = self.cache.key(text)
                if not key or key in seen or key in self._inflight:
                    continue
                if self._failed_until.get(key, 0.0) > now:
                    continue
                seen.add(key)
                self._inflight.add(key)
                batch.append(text)
            if not batch:
                return False
            context = list(self._context)
            self.stats["requests"] += 1
            self.stats["items"] += len(batch)
            future = self._pool.submit(self._run, batch, context)
            self._futures.append(future)
        return True

    def drain(self) -> int:
        """Fold finished batches into the cache. Returns items translated."""
        with self._lock:
            done = [f for f in self._futures if f.done()]
            self._futures = [f for f in self._futures if not f.done()]
        translated = 0
        for future in done:
            texts, results, error = future.result()
            now = time.monotonic()
            with self._lock:
                for text, result in zip(texts, results):
                    key = self.cache.key(text)
                    self._inflight.discard(key)
                    if result:
                        self.cache.put(text, self.target_lang, result)
                        self._context.append((text, result))
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

    def _run(
        self, texts: list[str], context: list[tuple[str, str]]
    ) -> tuple[list[str], list[str | None], Exception | None]:
        request = TranslationRequest(
            texts=texts, source_lang=self.source_lang, target_lang=self.target_lang, context=context
        )
        try:
            results = self.translator.translate(request)
        except Exception as exc:  # any backend failure: cool down the whole batch
            return texts, [None] * len(texts), exc
        if len(results) != len(texts):
            return texts, [None] * len(texts), RuntimeError("translator returned a wrong number of items")
        return texts, results, None
