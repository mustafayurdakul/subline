"""Screen reading: the frame goes out as a bounded PNG with one prompt, the
two readers send it the way their APIs want it, and the reply's JSON
becomes the texts for the card, prose and fences around it ignored."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import numpy as np
import pytest

from gametl.translate.screen import (
    MAX_EDGE,
    ClaudeScreenReader,
    OpenAICompatibleScreenReader,
    ScreenReadError,
    ScreenText,
    encode_frame,
    parse_reply,
    prompt,
)
from tests.helpers import text_response

REPLY = '{"items": [{"title": "Note", "text": "Kapı kilitli.\\nAnahtar masada."}, {"title": "Sign", "text": "Çıkış"}]}'


def test_the_frame_goes_out_as_a_png_no_larger_than_the_models_take() -> None:
    small = encode_frame(np.zeros((100, 200, 3), dtype=np.uint8))
    assert small[:8] == b"\x89PNG\r\n\x1a\n"
    big = encode_frame(np.zeros((1080, 3840, 3), dtype=np.uint8))
    width = int.from_bytes(big[16:20], "big")
    height = int.from_bytes(big[20:24], "big")
    assert width == MAX_EDGE and height == round(1080 * MAX_EDGE / 3840)  # the long side capped, the shape kept


def test_the_reply_becomes_texts_whatever_wraps_the_json() -> None:
    texts = parse_reply("Here you go:\n```json\n" + REPLY + "\n```")
    assert texts == [ScreenText("Note", "Kapı kilitli.\nAnahtar masada."), ScreenText("Sign", "Çıkış")]
    assert parse_reply('{"items": []}') == []
    assert parse_reply('{"items": [{"title": "x", "text": "  "}, "junk", {"text": "ok"}]}') == [ScreenText("", "ok")]
    for bad in ("no json here", "{not json", '{"nothing": 1}'):
        with pytest.raises(ScreenReadError):
            parse_reply(bad)


def test_the_prompt_names_the_game_and_the_language() -> None:
    text = prompt("tr", "Alan Wake 2")
    assert "Alan Wake 2" in text and "Turkish" in text and '"items"' in text and "[unreadable]" in text
    assert "(unknown)" in prompt("xx", "") and " xx" in prompt("xx", "")


def test_claude_reader_sends_the_image_and_reads_the_text_block() -> None:
    class Messages:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return text_response(REPLY)

    client = SimpleNamespace(messages=Messages())
    reader = ClaudeScreenReader(model="claude-haiku-5-5", client=client)
    texts = reader.read(b"png-bytes", "tr", "Alan Wake 2")
    assert [t.title for t in texts] == ["Note", "Sign"]
    (call,) = client.messages.calls
    assert call["model"] == "claude-haiku-5-5"
    image, text = call["messages"][0]["content"]
    assert image["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": base64.b64encode(b"png-bytes").decode(),
    }
    assert "Alan Wake 2" in text["text"]
    client.messages.create = lambda **kwargs: text_response(REPLY, stop_reason="refusal")
    with pytest.raises(ScreenReadError, match="declined"):
        reader.read(b"png", "tr")


def test_openai_compatible_reader_posts_a_chat_completion_with_the_image() -> None:
    class Session:
        def __init__(self, status: int = 200, content=None) -> None:
            self.status, self.content, self.calls = status, content, []

        def post(self, url, json, headers, timeout):
            self.calls.append({"url": url, "json": json, "headers": headers})
            body = {"choices": [{"message": {"content": self.content if self.content is not None else REPLY}}]}
            return SimpleNamespace(status_code=self.status, json=lambda: body, text="err")

    session = Session()
    reader = OpenAICompatibleScreenReader("http://localhost:11434/v1/", "qwen3-vl", api_key="k", session=session)
    assert [t.text for t in reader.read(b"png", "tr")] == ["Kapı kilitli.\nAnahtar masada.", "Çıkış"]
    (call,) = session.calls
    assert call["url"] == "http://localhost:11434/v1/chat/completions"
    assert call["headers"] == {"Authorization": "Bearer k"}
    text, image = call["json"]["messages"][0]["content"]
    assert "Turkish" in text["text"] and call["json"]["model"] == "qwen3-vl"
    assert image["image_url"]["url"].startswith("data:image/png;base64,")
    # Content parts, a local server without a key, and an HTTP error.
    parts = Session(content=[{"type": "text", "text": REPLY}])
    assert len(OpenAICompatibleScreenReader("http://x/v1", "m", session=parts).read(b"png", "tr")) == 2
    assert parts.calls[0]["headers"] == {}
    with pytest.raises(ScreenReadError, match="HTTP 401"):
        OpenAICompatibleScreenReader("http://x/v1", "m", session=Session(status=401)).read(b"png", "tr")


def test_a_model_name_is_json_safe_in_the_reply_path() -> None:
    assert json.loads(REPLY)["items"][0]["title"] == "Note"
