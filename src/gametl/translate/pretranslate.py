"""Pre-translate a game's script into the per-game cache, so lines show
their translation the moment OCR reads them.

Input: a text file (one line per entry), an .srt subtitle file, a JSON file
(list of strings, or any object whose string values are the lines), or a
CSV (a "text"/"source"/"line" column, else the first column).

Two ways to run it: synchronously through the normal API in chunks, or
through the Message Batches API (half price, results within minutes to an
hour; the batch id is saved so collection can resume later).
"""

from __future__ import annotations

import csv
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import TranslationRequest
from .cache import TranslationCache
from .claude import ClaudeTranslator, supports_disabled_thinking

_SRT_TIMING = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+")
_TAGS = re.compile(r"<[^>]+>|\{[^}]+\}")


# -- loading ----------------------------------------------------------------------


def load_lines(path: Path | str) -> list[str]:
    path = Path(path)
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")
    if suffix == ".srt":
        raw = _load_srt(text)
    elif suffix == ".json":
        raw = _flatten_strings(json.loads(text))
    elif suffix == ".csv":
        raw = _load_csv(text)
    else:
        raw = text.splitlines()
    seen: set[str] = set()
    lines: list[str] = []
    for line in raw:
        cleaned = _TAGS.sub("", line).strip()
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            lines.append(cleaned)
    return lines


def _load_srt(text: str) -> list[str]:
    entries: list[str] = []
    block: list[str] = []
    for line in [*text.splitlines(), ""]:
        stripped = line.strip()
        if not stripped:
            if block:
                entries.append("\n".join(block))
                block = []
            continue
        if stripped.isdigit() and not block:
            continue
        if _SRT_TIMING.match(stripped):
            continue
        block.append(stripped)
    return entries


def _flatten_strings(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _flatten_strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _flatten_strings(v)]
    return []


def _load_csv(text: str) -> list[str]:
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    column = next((i for i, h in enumerate(header) if h in ("text", "source", "line", "string")), None)
    body = rows[1:] if column is not None else rows
    column = column or 0
    return [row[column] for row in body if len(row) > column]


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), max(1, size))]


# -- synchronous ------------------------------------------------------------------


def pretranslate_sync(
    lines: list[str],
    translator: ClaudeTranslator,
    cache: TranslationCache,
    target_lang: str,
    chunk_size: int = 20,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Translate `lines` not yet in `cache` through the normal API. Returns
    the number of lines added."""
    say = progress or (lambda _s: None)
    todo = [ln for ln in lines if cache.get(ln, target_lang) is None]
    say(f"{len(lines)} lines, {len(todo)} to translate")
    added = 0
    for i, chunk in enumerate(chunked(todo, chunk_size)):
        results = translator.translate(TranslationRequest(chunk, translator.source_lang, target_lang))
        for source, translated in zip(chunk, results, strict=True):
            if translated:
                cache.put(source, target_lang, translated)
                added += 1
        cache.save()
        say(f"chunk {i + 1}/{(len(todo) + chunk_size - 1) // chunk_size}: {added} translated")
    return added


# -- batches API ------------------------------------------------------------------


@dataclass
class BatchJob:
    batch_id: str
    target_lang: str
    chunks: dict[str, list[str]] = field(default_factory=dict)  # custom_id -> source lines

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"batch_id": self.batch_id, "target_lang": self.target_lang, "chunks": self.chunks}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> BatchJob:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data["batch_id"], data["target_lang"], data["chunks"])


def build_batch_requests(
    lines: list[str], translator: ClaudeTranslator, target_lang: str, chunk_size: int = 20
) -> tuple[list[dict], dict[str, list[str]]]:
    """Batches API request dicts (plain-JSON reply mode) and the chunk map."""
    requests: list[dict] = []
    chunks: dict[str, list[str]] = {}
    for i, chunk in enumerate(chunked(lines, chunk_size)):
        custom_id = f"chunk-{i:05d}"
        chunks[custom_id] = chunk
        request = TranslationRequest(chunk, translator.source_lang, target_lang)
        params: dict[str, Any] = {
            "model": translator.model,
            "max_tokens": translator.max_tokens,
            "system": translator.system_blocks(translator.source_lang, target_lang),
            "messages": [{"role": "user", "content": translator.user_payload(request)}],
            "output_config": {"effort": translator.effort},
        }
        if translator.thinking == "disabled" and supports_disabled_thinking(translator.model):
            params["thinking"] = {"type": "disabled"}
        requests.append({"custom_id": custom_id, "params": params})
    return requests, chunks


def submit_batch(
    lines: list[str],
    translator: ClaudeTranslator,
    cache: TranslationCache,
    target_lang: str,
    chunk_size: int = 20,
    client: Any = None,
) -> BatchJob | None:
    """Create a batch for the lines not in the cache. None when nothing to do."""
    if translator.structured:
        raise ValueError("batch pre-translation needs the plain-JSON reply mode (structured=False)")
    todo = [ln for ln in lines if cache.get(ln, target_lang) is None]
    if not todo:
        return None
    requests, chunks = build_batch_requests(todo, translator, target_lang, chunk_size)
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    batch = client.messages.batches.create(requests=requests)
    return BatchJob(batch.id, target_lang, chunks)


def collect_batch(
    job: BatchJob,
    cache: TranslationCache,
    client: Any = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[bool, int, int]:
    """Fetch a batch's results into the cache. Returns (ended, lines added,
    failed chunks). When the batch has not ended, nothing is collected yet."""
    say = progress or (lambda _s: None)
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    batch = client.messages.batches.retrieve(job.batch_id)
    if batch.processing_status != "ended":
        counts = batch.request_counts
        say(
            f"batch {job.batch_id}: {batch.processing_status}, "
            f"processing {counts.processing}, succeeded {counts.succeeded}"
        )
        return False, 0, 0
    added = failed = 0
    for result in client.messages.batches.results(job.batch_id):
        sources = job.chunks.get(result.custom_id)
        if sources is None:
            continue
        if result.result.type != "succeeded":
            failed += 1
            error = getattr(result.result, "error", None)
            detail = f": {getattr(error, 'message', error)}" if error is not None else ""
            say(f"{result.custom_id}: {result.result.type}{detail}")
            continue
        message = result.result.message
        try:
            parsed = ClaudeTranslator._parse_text_json(message)
        except Exception as exc:  # malformed reply for this chunk only
            failed += 1
            say(f"{result.custom_id}: unreadable reply ({exc})")
            continue
        for item in parsed.items:
            if 0 <= item.id < len(sources) and item.text.strip():
                cache.put(sources[item.id], job.target_lang, item.text)
                added += 1
    cache.save()
    return True, added, failed


def wait_for_batch(
    job: BatchJob,
    cache: TranslationCache,
    timeout: float,
    poll: float = 20.0,
    client: Any = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[bool, int, int]:
    deadline = time.monotonic() + timeout
    while True:
        ended, added, failed = collect_batch(job, cache, client, progress)
        if ended or time.monotonic() >= deadline:
            return ended, added, failed
        time.sleep(poll)
