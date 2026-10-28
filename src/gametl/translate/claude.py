"""Claude translation backend (Anthropic Python SDK).

One request per batch: the system prompt (fixed per session, cache-marked)
carries the rules, the game name, tone notes and the glossary; the user
message is a JSON document with the target language, recent context and
the items; the reply is JSON parsed into `TranslationBatch`.

Two reply modes. Default: the prompt asks for a JSON list and the text is
parsed here (malformed output raises TranslationError and the batch is
retried after a cooldown). Optional `structured=True` uses server-side
structured output, which guarantees the shape but measured about 0.5 s
slower per call on Haiku 5.5 (PLAN.md section 11).

Model notes (Claude Haiku 5.5, the default): thinking is sent as disabled
(allowed at effort low to high) since it measured no quality gain here;
`output_config.effort` stays "low"; no sampling parameters (they 400); a
`refusal` stop reason has no server-side fallback and surfaces as a
TranslationError.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from .base import TranslationError, TranslationRequest, language_name


class TranslatedItem(BaseModel):
    id: int
    text: str


class TranslationBatch(BaseModel):
    items: list[TranslatedItem]


_SYSTEM_RULES = "\n".join(
    [
        "Translate text captured by OCR from a video game screen{source_clause} into {target}.",
        "Keep the meaning, tone and register of game dialogue; items may also be UI labels or HUD text.",
        "Keep each translation about as long as its source (it must fit the same space), keep its line breaks "
        "(N lines in, N out), and keep numbers, units, symbols, placeholders and proper names unless the glossary "
        "says otherwise.",
        "Items may contain OCR errors (l/1, O/0, spacing): translate the intended text.",
        '"context" holds recent lines with their translations, oldest first; use it only for consistency.',
        "Reply with JSON only, no notes.",
    ]
)

_PLAIN_FORMAT = (
    '\nReply exactly as {"items": ["<translation of item 0>", "<translation of item 1>", ...]}: '
    "one string per item, same order and count."
)

# USD per million tokens: (input, output, cache read, cache write), prompts <= 100K tokens.
PRICES_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.40, 5.00),
}


def estimate_cost_usd(model: str, totals: dict[str, int]) -> float | None:
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    inp, out, cread, cwrite = prices
    return (
        totals["input"] * inp + totals["output"] * out + totals["cache_read"] * cread + totals["cache_write"] * cwrite
    ) / 1_000_000


def supports_disabled_thinking(model: str) -> bool:
    """Claude Haiku 5.5 and Claude Opus 5 accept thinking=disabled at effort
    high or below; Claude Opus 5.5 and Claude Sonnet 5.5 return 400 for it
    (thinking stays adaptive there, effort is the only lever)."""
    model = model.lower()
    if model.startswith(("claude-opus-5-5", "claude-sonnet-5-5")):
        return False
    return model.startswith(("claude-haiku-5-5", "claude-opus-5"))


class ClaudeTranslator:
    name = "claude"

    def __init__(
        self,
        model: str = "claude-haiku-5-5",
        effort: str = "low",
        thinking: str = "disabled",  # "disabled" | "adaptive"
        game: str | None = None,
        glossary: dict[str, str] | None = None,
        tone: str | None = None,  # notes on tone and formality
        source_lang: str | None = None,
        max_tokens: int = 2048,
        timeout: float = 20.0,
        structured: bool = False,  # True: server-side structured output (measured ~0.5 s slower per call)
        api_key: str | None = None,  # None: the SDK reads ANTHROPIC_API_KEY itself
        client: Any = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.thinking = thinking
        self.structured = structured
        self.game = game
        self.glossary = dict(glossary or {})
        self.tone = tone
        self.source_lang = source_lang
        self.max_tokens = max_tokens
        self.last_usage: Any = None
        self.calls = 0
        self.usage_totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        self._system_cache: dict[tuple[str | None, str], list[dict[str, Any]]] = {}

        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)
        self.client = client  # also used by batch pre-translation, so the same key serves both

    # -- prompt ----------------------------------------------------------------

    def system_blocks(self, source_lang: str | None, target_lang: str) -> list[dict[str, Any]]:
        """Fixed per (source, target) so the prefix stays cacheable."""
        key = (source_lang, target_lang)
        cached = self._system_cache.get(key)
        if cached is not None:
            return cached
        source = language_name(source_lang)
        target = language_name(target_lang) or target_lang
        text = _SYSTEM_RULES.format(target=target, source_clause=f" from {source}" if source else "")
        extras: list[str] = []
        if self.game:
            extras.append(f"Game: {self.game}.")
        if self.tone:
            extras.append(f"Style notes: {self.tone}")
        if self.glossary:
            lines = "\n".join(f"- {k} -> {v}" for k, v in sorted(self.glossary.items()))
            extras.append("Glossary (always use these renderings):\n" + lines)
        if extras:
            text += "\n" + "\n".join(extras)
        if not self.structured:
            text += _PLAIN_FORMAT
        blocks = [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
        self._system_cache[key] = blocks
        return blocks

    def user_payload(self, request: TranslationRequest) -> str:
        """Plain mode sends the items as a positional list (fewer tokens in
        and out); structured mode keeps numbered objects to match the schema."""
        payload: dict[str, Any] = {
            "target_language": language_name(request.target_lang) or request.target_lang,
        }
        if request.context:  # the last few pairs: enough for consistency, cheap in tokens
            payload["context"] = [[source, target] for source, target in request.context[-10:]]
        if self.structured:
            payload["items"] = [{"id": i, "text": t} for i, t in enumerate(request.texts)]
        else:
            payload["items"] = list(request.texts)
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _parse_text_json(response: Any) -> TranslationBatch:
        """Plain-JSON mode: the answer is the first text block (after any
        thinking blocks), possibly wrapped in a code fence."""
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
        # The object between the outermost braces: a code fence or chatter
        # around it is ignored by the slice itself.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            raise TranslationError("no JSON object in response text")
        try:
            data = json.loads(text[start : end + 1])
        except ValueError as exc:
            raise TranslationError(f"malformed JSON in response: {exc}") from exc
        items = data.get("items")
        if not isinstance(items, list):
            raise TranslationError("no items list in response")
        parsed: list[TranslatedItem] = []
        try:
            for index, item in enumerate(items):
                if isinstance(item, str):
                    parsed.append(TranslatedItem(id=index, text=item))
                elif isinstance(item, dict) and "text" in item:
                    parsed.append(TranslatedItem(id=int(item.get("id", index)), text=str(item["text"])))
                else:
                    raise TranslationError(f"unexpected item in response: {item!r}")
        except (ValueError, TypeError) as exc:
            raise TranslationError(f"malformed items in response: {exc}") from exc
        return TranslationBatch(items=parsed)

    @staticmethod
    def results_from(batch: TranslationBatch, count: int) -> list[str | None]:
        """The batch's texts back in input order; a missing or blank item
        stays None (retried later)."""
        out: list[str | None] = [None] * count
        for item in batch.items:
            if 0 <= item.id < count and item.text.strip():
                out[item.id] = item.text
        return out

    def request_params(self, request: TranslationRequest) -> dict[str, Any]:
        """The Messages API call for `request`: cached system prompt, one user
        message with the items, and the thinking and output settings."""
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system_blocks(request.source_lang or self.source_lang, request.target_lang),
            "messages": [{"role": "user", "content": self.user_payload(request)}],
            "output_config": {"effort": self.effort},
        }
        if self.structured:
            params["output_format"] = TranslationBatch
        if self.thinking == "disabled" and supports_disabled_thinking(self.model):
            params["thinking"] = {"type": "disabled"}
        return params

    # -- call ------------------------------------------------------------------

    def translate(self, request: TranslationRequest) -> list[str | None]:
        if not request.texts:
            return []
        kwargs = self.request_params(request)

        try:
            import anthropic
        except ImportError:  # pragma: no cover - the stub client path in tests
            anthropic = None  # type: ignore[assignment]

        try:
            if self.structured:
                response = self.client.messages.parse(**kwargs)
            else:
                response = self.client.messages.create(**kwargs)
        except Exception as exc:
            if anthropic is not None and isinstance(exc, (anthropic.APIConnectionError, anthropic.APIStatusError)):
                raise TranslationError(f"{type(exc).__name__}: {exc}") from exc
            raise

        # Token accounting for the cost estimate, then the stop reasons that mean failure.
        self.calls += 1
        self.last_usage = usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage_totals["input"] += getattr(usage, "input_tokens", 0) or 0
            self.usage_totals["output"] += getattr(usage, "output_tokens", 0) or 0
            self.usage_totals["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
            self.usage_totals["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            details = getattr(response, "stop_details", None)
            raise TranslationError(f"model declined the batch ({getattr(details, 'category', None)})")
        if stop == "max_tokens":
            raise TranslationError("response cut off at max_tokens")

        if self.structured:
            batch = getattr(response, "parsed_output", None)
            if batch is None:
                raise TranslationError("no structured output in response")
        else:
            batch = self._parse_text_json(response)
        return self.results_from(batch, len(request.texts))
