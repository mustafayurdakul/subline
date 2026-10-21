"""Claude translation backend (Anthropic Python SDK).

One request per batch: the system prompt (fixed per session, cache-marked)
carries the rules, the game name and the glossary; the user message is a JSON
document with the target language, recent context and the numbered items;
the reply is a JSON object parsed into `TranslationBatch`.

Two reply modes. Default: the prompt asks for JSON and the text is parsed
here (malformed output raises TranslationError and the batch is retried
after a cooldown). Optional `structured=True` uses server-side structured
output, which guarantees the shape but measured about 0.5 s slower per call
on Haiku 5.5 (benchmark in PLAN.md section 11).

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


_SYSTEM_RULES = """You translate text captured by OCR from a video game screen, so the player can read the game in {target}.

Rules:
- Translate every item{source_clause} into {target}. Return each id exactly once.
- Game dialogue may be informal, dramatic, abbreviated or in character; keep the meaning, tone and register.
- The translation must fit in the same space on screen: keep it about as long as the source, preferring shorter phrasing.
- Keep line breaks: a source with N lines gets a translation with N lines, broken at similar points.
- Keep numbers, units, symbols, placeholders and proper names, unless the glossary says otherwise.
- Items are OCR output and may contain small errors (l/1, O/0, missing or extra spaces); translate the intended text.
- Items may be UI labels, menu entries or HUD text, not only sentences; translate them as UI text.
- Use the "context" field (recent lines and their translations, oldest first) only for consistency of names and terms.
- Return only the JSON. No notes, no explanations, no transliteration guides."""


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


class ClaudeTranslator:
    name = "claude"

    def __init__(
        self,
        model: str = "claude-haiku-5-5",
        effort: str = "low",
        thinking: str = "disabled",  # "disabled" | "adaptive"
        game: str | None = None,
        glossary: dict[str, str] | None = None,
        style: str | None = None,
        source_lang: str | None = None,
        target_lang: str = "tr",
        max_tokens: int = 2048,
        timeout: float = 20.0,
        structured: bool = False,  # True: server-side structured output (measured ~0.5 s slower per call)
        client: Any = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.thinking = thinking
        self.structured = structured
        self.game = game
        self.glossary = dict(glossary or {})
        self.style = style
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.max_tokens = max_tokens
        self.last_usage: Any = None
        self.calls = 0
        self.usage_totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        self._system_cache: dict[tuple[str | None, str], list[dict[str, Any]]] = {}

        if client is None:
            import anthropic

            client = anthropic.Anthropic(timeout=timeout, max_retries=1)
        self._client = client

    # -- prompt ----------------------------------------------------------------

    def system_blocks(self, source_lang: str | None, target_lang: str) -> list[dict[str, Any]]:
        """Fixed per (source, target) so the prefix stays cacheable."""
        key = (source_lang, target_lang)
        cached = self._system_cache.get(key)
        if cached is not None:
            return cached
        source = language_name(source_lang)
        target = language_name(target_lang) or target_lang
        text = _SYSTEM_RULES.format(
            target=target,
            source_clause=f" from {source}" if source else "",
        )
        extras: list[str] = []
        if self.game:
            extras.append(f"Game: {self.game}.")
        if self.style:
            extras.append(f"Style notes: {self.style}")
        if self.glossary:
            lines = "\n".join(f"- {k} -> {v}" for k, v in sorted(self.glossary.items()))
            extras.append("Glossary (always use these renderings):\n" + lines)
        if extras:
            text += "\n\n" + "\n".join(extras)
        if not self.structured:
            text += (
                '\n\nReply with exactly one JSON object and nothing else: '
                '{"items": [{"id": <id>, "text": "<translation>"}, ...]}'
            )
        blocks = [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
        self._system_cache[key] = blocks
        return blocks

    @staticmethod
    def user_payload(request: TranslationRequest) -> str:
        payload = {
            "target_language": language_name(request.target_lang) or request.target_lang,
            "context": [{"source": s, "translation": t} for s, t in (request.context or [])],
            "items": [{"id": i, "text": t} for i, t in enumerate(request.texts)],
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _parse_text_json(response: Any) -> TranslationBatch:
        """Plain-JSON mode: the answer is the first text block (after any
        thinking blocks), possibly wrapped in a code fence."""
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            raise TranslationError("no JSON object in response text")
        try:
            return TranslationBatch.model_validate(json.loads(text[start : end + 1]))
        except (ValueError, TypeError) as exc:
            raise TranslationError(f"malformed JSON in response: {exc}") from exc

    # -- call ------------------------------------------------------------------

    def translate(self, request: TranslationRequest) -> list[str | None]:
        if not request.texts:
            return []
        source_lang = request.source_lang or self.source_lang
        target_lang = request.target_lang or self.target_lang

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system_blocks(source_lang, target_lang),
            "messages": [{"role": "user", "content": self.user_payload(request)}],
            "output_config": {"effort": self.effort},
        }
        if self.structured:
            kwargs["output_format"] = TranslationBatch
        if self.thinking == "disabled":
            kwargs["thinking"] = {"type": "disabled"}

        try:
            import anthropic
        except ImportError:  # pragma: no cover - the stub client path in tests
            anthropic = None  # type: ignore[assignment]

        try:
            if self.structured:
                response = self._client.messages.parse(**kwargs)
            else:
                response = self._client.messages.create(**kwargs)
        except Exception as exc:
            if anthropic is not None and isinstance(exc, (anthropic.APIConnectionError, anthropic.APIStatusError)):
                raise TranslationError(f"{type(exc).__name__}: {exc}") from exc
            raise

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

        out: list[str | None] = [None] * len(request.texts)
        for item in batch.items:
            if 0 <= item.id < len(out) and item.text.strip():
                out[item.id] = item.text
        return out
