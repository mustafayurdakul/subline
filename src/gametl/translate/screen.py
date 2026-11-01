"""Screen reading: a vision model reads a whole game frame and translates
what a player would want translated (a note, a letter, a sign, a menu),
on a hotkey. One call per press, nothing continuous: a vision call takes a
second or three, which the live subtitle path cannot afford and the chat
card does not mind.

Two readers, the same prompt and reply: Claude through the Anthropic SDK,
and any OpenAI-compatible chat endpoint (OpenAI, Gemini, Mistral,
OpenRouter, a local Ollama or LM Studio), which covers the people who do
not want Claude.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import numpy as np

from .base import language_name

MAX_EDGE = 1568  # px: what the models downscale to anyway; sending more only costs upload time
_JSON = re.compile(r"\{.*\}", re.DOTALL)

_PROMPT = (
    "This is a screenshot from the video game {game}. Find every piece of text in it that a player would want "
    "translated: dialogue, documents, notes, letters, signs, menus, item descriptions, tutorial messages. Skip HUD "
    "numbers, button prompts and decoration. Translate each into {target}, keeping paragraphs (separated by a "
    "newline) and the reading order. Where a part cannot be read, write [unreadable] rather than guessing. "
    'Reply with JSON only: {{"items": [{{"title": "<what it is, two words at most, e.g. Note, Letter, Sign, '
    'Dialogue, Menu>", "text": "<the translation>"}}]}}; an empty list when there is nothing to translate.'
)


@dataclass(slots=True)
class ScreenText:
    """One thing read off the screen: what it is, and its translation."""

    title: str
    text: str


class ScreenReadError(RuntimeError):
    """The read failed, with a message fit for the status line."""


class ScreenReader(Protocol):
    name: str

    def read(self, png: bytes, target_lang: str, game: str = "") -> list[ScreenText]: ...


def encode_frame(image_bgr: np.ndarray) -> bytes:
    """A captured frame as PNG, no longer than MAX_EDGE on its long side."""
    height, width = image_bgr.shape[:2]
    scale = MAX_EDGE / max(width, height)
    if scale < 1:
        image_bgr = cv2.resize(image_bgr, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode(".png", image_bgr)
    if not ok:
        raise ScreenReadError("could not encode the frame")
    return data.tobytes()


def prompt(target_lang: str, game: str) -> str:
    return _PROMPT.format(game=game or "(unknown)", target=language_name(target_lang) or target_lang)


def parse_reply(text: str) -> list[ScreenText]:
    """The items of a reply, from the JSON object in it (models sometimes
    wrap it in prose or a code fence)."""
    match = _JSON.search(text or "")
    if match is None:
        raise ScreenReadError("the model's reply held no JSON")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise ScreenReadError(f"the model's reply was not valid JSON: {exc}") from exc
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ScreenReadError('the model\'s reply had no "items" list')
    texts: list[ScreenText] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        body = " ".join(str(item.get("text") or "").split(" ")).strip()
        if body:
            texts.append(ScreenText(str(item.get("title") or "").strip(), body))
    return texts


class ClaudeScreenReader:
    name = "claude"

    def __init__(
        self, model: str = "claude-haiku-5-5", api_key: str | None = None, client: Any = None, timeout: float = 60.0
    ) -> None:
        self.model = model
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)
        self.client = client

    def read(self, png: bytes, target_lang: str, game: str = "") -> list[ScreenText]:
        image = {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode("ascii")}
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": image},
                        {"type": "text", "text": prompt(target_lang, game)},
                    ],
                }
            ],
        }
        try:
            response = self.client.messages.create(**params)
        except Exception as exc:  # network, key, quota: all read the same to the player
            raise ScreenReadError(f"{type(exc).__name__}: {exc}") from exc
        if getattr(response, "stop_reason", None) == "refusal":
            raise ScreenReadError("the model declined to read the screen")
        text = "".join(getattr(block, "text", "") for block in getattr(response, "content", []) or [])
        return parse_reply(text)


class OpenAICompatibleScreenReader:
    """Any chat-completions endpoint that takes an image: OpenAI, Gemini's
    OpenAI-compatible endpoint, Mistral, OpenRouter, Ollama, LM Studio."""

    name = "openai"

    def __init__(
        self, base_url: str, model: str, api_key: str | None = None, session: Any = None, timeout: float = 90.0
    ) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        if session is None:
            import requests

            session = requests.Session()
        self._session = session

    def read(self, png: bytes, target_lang: str, game: str = "") -> list[ScreenText]:
        data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt(target_lang, game)},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            response = self._session.post(self.url, json=body, headers=headers, timeout=self.timeout)
        except Exception as exc:
            raise ScreenReadError(f"request failed: {exc}") from exc
        if response.status_code != 200:
            raise ScreenReadError(f"HTTP {response.status_code}: {response.text[:200]}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ScreenReadError("the reply was not a chat completion") from exc
        if isinstance(content, list):  # some servers return content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return parse_reply(str(content))
