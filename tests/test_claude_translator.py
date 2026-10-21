"""ClaudeTranslator against a stub client: request shape and result mapping,
no network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from gametl.translate.base import TranslationError, TranslationRequest
from gametl.translate.claude import ClaudeTranslator, TranslationBatch, TranslatedItem


class StubMessages:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class StubClient:
    def __init__(self, response) -> None:
        self.messages = StubMessages(response)


def response_with(items, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        parsed_output=TranslationBatch(items=[TranslatedItem(id=i, text=t) for i, t in items]),
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
    )


def test_request_shape_and_result_order() -> None:
    client = StubClient(response_with([(1, "Kapıyı açma demiştim."), (0, "Yakın dur.")]))
    translator = ClaudeTranslator(
        game="Fake Game",
        glossary={"Ammo": "Mühimmat"},
        source_lang="en",
        target_lang="tr",
        client=client,
    )
    out = translator.translate(
        TranslationRequest(
            texts=["Stay close.", "I told you not to open that door."],
            source_lang="en",
            target_lang="tr",
            context=[("Hello", "Merhaba")],
        )
    )
    assert out == ["Yakın dur.", "Kapıyı açma demiştim."]

    (call,) = client.messages.calls
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_config"] == {"effort": "low"}
    assert call["output_format"] is TranslationBatch
    assert "thinking" not in call
    assert "temperature" not in call

    system_text = call["system"][0]["text"]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "from English into Turkish" in system_text
    assert "Game: Fake Game." in system_text
    assert "Ammo -> Mühimmat" in system_text

    (message,) = call["messages"]
    assert message["role"] == "user"
    payload = json.loads(message["content"])
    assert payload["target_language"] == "Turkish"
    assert payload["items"] == [
        {"id": 0, "text": "Stay close."},
        {"id": 1, "text": "I told you not to open that door."},
    ]
    assert payload["context"] == [{"source": "Hello", "translation": "Merhaba"}]


def test_system_prompt_is_stable_across_calls() -> None:
    client = StubClient(response_with([(0, "x")]))
    translator = ClaudeTranslator(client=client, source_lang="en", target_lang="tr")
    translator.translate(TranslationRequest(["a"], target_lang="tr"))
    translator.translate(TranslationRequest(["b"], target_lang="tr", context=[("a", "x")]))
    first, second = client.messages.calls
    assert first["system"] == second["system"]  # cacheable prefix


def test_missing_or_blank_items_become_none() -> None:
    client = StubClient(response_with([(0, "Merhaba"), (1, "   "), (7, "ignored")]))
    translator = ClaudeTranslator(client=client)
    out = translator.translate(TranslationRequest(["Hello", "Hi", "Hey"], target_lang="tr"))
    assert out == ["Merhaba", None, None]


def test_disabled_thinking_is_sent_when_asked() -> None:
    client = StubClient(response_with([(0, "x")]))
    translator = ClaudeTranslator(client=client, thinking="disabled", effort="low")
    translator.translate(TranslationRequest(["a"], target_lang="tr"))
    assert client.messages.calls[0]["thinking"] == {"type": "disabled"}


def test_refusal_and_cutoff_raise() -> None:
    translator = ClaudeTranslator(client=StubClient(response_with([], stop_reason="refusal")))
    with pytest.raises(TranslationError):
        translator.translate(TranslationRequest(["a"], target_lang="tr"))
    translator = ClaudeTranslator(client=StubClient(response_with([], stop_reason="max_tokens")))
    with pytest.raises(TranslationError):
        translator.translate(TranslationRequest(["a"], target_lang="tr"))


def test_empty_batch_makes_no_call() -> None:
    client = StubClient(response_with([]))
    assert ClaudeTranslator(client=client).translate(TranslationRequest([], target_lang="tr")) == []
    assert client.messages.calls == []
