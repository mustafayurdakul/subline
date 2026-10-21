"""Claude translation backend (Anthropic Python SDK).

One request per batch: the system prompt (fixed per session, cache-marked)
carries the rules, the game name and the glossary; the user message is a JSON
document with the target language, recent context and the numbered items;
the reply is structured JSON parsed into `TranslationBatch`.

Model notes (Claude Haiku 5.5, the default): adaptive thinking is on by
default and `effort` is the lever for latency, so this sends
`output_config.effort` (default "low"); no sampling parameters (they 400); a
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


class ClaudeTranslator:
    name = "claude"

    def __init__(
        self,
        model: str = "claude-haiku-5-5",
        effort: str = "low",
        thinking: str = "adaptive",  # "adaptive" | "disabled"
        game: str | None = None,
        glossary: dict[str, str] | None = None,
        style: str | None = None,
        source_lang: str | None = None,
        target_lang: str = "tr",
        max_tokens: int = 2048,
        timeout: float = 20.0,
        client: Any = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.thinking = thinking
        self.game = game
        self.glossary = dict(glossary or {})
        self.style = style
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.max_tokens = max_tokens
        self.last_usage: Any = None
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
            "output_format": TranslationBatch,
            "output_config": {"effort": self.effort},
        }
        if self.thinking == "disabled":
            kwargs["thinking"] = {"type": "disabled"}

        try:
            import anthropic
        except ImportError:  # pragma: no cover - the stub client path in tests
            anthropic = None  # type: ignore[assignment]

        try:
            response = self._client.messages.parse(**kwargs)
        except Exception as exc:
            if anthropic is not None and isinstance(exc, (anthropic.APIConnectionError, anthropic.APIStatusError)):
                raise TranslationError(f"{type(exc).__name__}: {exc}") from exc
            raise

        self.last_usage = getattr(response, "usage", None)
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            details = getattr(response, "stop_details", None)
            raise TranslationError(f"model declined the batch ({getattr(details, 'category', None)})")
        if stop == "max_tokens":
            raise TranslationError("response cut off at max_tokens")

        batch = getattr(response, "parsed_output", None)
        if batch is None:
            raise TranslationError("no structured output in response")

        out: list[str | None] = [None] * len(request.texts)
        for item in batch.items:
            if 0 <= item.id < len(out) and item.text.strip():
                out[item.id] = item.text
        return out
