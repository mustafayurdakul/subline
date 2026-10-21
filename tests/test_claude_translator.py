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
        self.created: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    def create(self, **kwargs):
        self.created.append(kwargs)
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


def test_defaults_are_plain_json_without_thinking() -> None:
    body = '{"items": [{"id": 0, "text": "Merhaba"}]}'
    response = SimpleNamespace(
        stop_reason="end_turn",
        stop_details=None,
        content=[SimpleNamespace(type="text", text=body)],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client = StubClient(response)
    translator = ClaudeTranslator(client=client)
    assert translator.translate(TranslationRequest(["Hello"], target_lang="tr")) == ["Merhaba"]
    (call,) = client.messages.created
    assert client.messages.calls == []  # no parse(): plain mode
    assert "output_format" not in call
    assert call["thinking"] == {"type": "disabled"}
    assert call["output_config"] == {"effort": "low"}
    assert call["model"] == "claude-haiku-5-5"


def test_structured_request_shape_and_result_order() -> None:
    client = StubClient(response_with([(1, "Kapıyı açma demiştim."), (0, "Yakın dur.")]))
    translator = ClaudeTranslator(
        game="Fake Game",
        glossary={"Ammo": "Mühimmat"},
        source_lang="en",
        target_lang="tr",
        structured=True,
        thinking="adaptive",
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
    translator = ClaudeTranslator(client=client, source_lang="en", target_lang="tr", structured=True)
    translator.translate(TranslationRequest(["a"], target_lang="tr"))
    translator.translate(TranslationRequest(["b"], target_lang="tr", context=[("a", "x")]))
    first, second = client.messages.calls
    assert first["system"] == second["system"]  # cacheable prefix


def test_missing_or_blank_items_become_none() -> None:
    client = StubClient(response_with([(0, "Merhaba"), (1, "   "), (7, "ignored")]))
    translator = ClaudeTranslator(client=client, structured=True)
    out = translator.translate(TranslationRequest(["Hello", "Hi", "Hey"], target_lang="tr"))
    assert out == ["Merhaba", None, None]


def test_disabled_thinking_is_not_sent_to_models_that_reject_it() -> None:
    from gametl.translate.claude import supports_disabled_thinking

    assert supports_disabled_thinking("claude-haiku-5-5")
    assert supports_disabled_thinking("claude-opus-5")
    assert not supports_disabled_thinking("claude-opus-5-5")
    assert not supports_disabled_thinking("claude-sonnet-5-5")
    client = StubClient(response_with([(0, "x")]))
    translator = ClaudeTranslator(client=client, model="claude-opus-5-5", thinking="disabled", structured=True)
    translator.translate(TranslationRequest(["a"], target_lang="tr"))
    assert "thinking" not in client.messages.calls[0]


def test_adaptive_thinking_omits_the_parameter() -> None:
    client = StubClient(response_with([(0, "x")]))
    translator = ClaudeTranslator(client=client, thinking="adaptive", structured=True)
    translator.translate(TranslationRequest(["a"], target_lang="tr"))
    assert "thinking" not in client.messages.calls[0]


def test_refusal_and_cutoff_raise() -> None:
    for mode in (True, False):
        translator = ClaudeTranslator(client=StubClient(response_with([], stop_reason="refusal")), structured=mode)
        with pytest.raises(TranslationError):
            translator.translate(TranslationRequest(["a"], target_lang="tr"))
        translator = ClaudeTranslator(client=StubClient(response_with([], stop_reason="max_tokens")), structured=mode)
        with pytest.raises(TranslationError):
            translator.translate(TranslationRequest(["a"], target_lang="tr"))


def test_malformed_plain_json_raises() -> None:
    response = SimpleNamespace(
        stop_reason="end_turn",
        stop_details=None,
        content=[SimpleNamespace(type="text", text="Sure! Here you go: not json")],
        usage=None,
    )
    translator = ClaudeTranslator(client=StubClient(response))
    with pytest.raises(TranslationError):
        translator.translate(TranslationRequest(["a"], target_lang="tr"))


def test_plain_json_mode_parses_text_block() -> None:
    body = '```json\n{"items": [{"id": 0, "text": "Merhaba"}, {"id": 1, "text": "Yakın dur."}]}\n```'
    response = SimpleNamespace(
        stop_reason="end_turn",
        stop_details=None,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=body)],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client = StubClient(response)
    translator = ClaudeTranslator(client=client, structured=False, source_lang="en", target_lang="tr")
    out = translator.translate(TranslationRequest(["Hello", "Stay close."], target_lang="tr"))
    assert out == ["Merhaba", "Yakın dur."]
    (call,) = client.messages.created
    assert "output_format" not in call
    assert "Reply with exactly one JSON object" in call["system"][0]["text"]
    assert client.messages.calls == []


def test_empty_batch_makes_no_call() -> None:
    client = StubClient(response_with([]))
    assert ClaudeTranslator(client=client).translate(TranslationRequest([], target_lang="tr")) == []
    assert client.messages.calls == [] and client.messages.created == []
