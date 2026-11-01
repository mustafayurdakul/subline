from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from gametl.app.pretranslate import positive_int
from gametl.translate.cache import TranslationCache
from gametl.translate.claude import ClaudeTranslator
from gametl.translate.pretranslate import (
    BatchJob,
    build_batch_requests,
    chunked,
    collect_batch,
    load_lines,
    pretranslate_sync,
    submit_batch,
)
from tests.helpers import text_response


def test_load_txt_dedupes_and_strips_tags(tmp_path: Path) -> None:
    f = tmp_path / "s.txt"
    f.write_text("Stay close.\n\n<i>Stay close.</i>\n  Open the door.  \n", encoding="utf-8")
    assert load_lines(f) == ["Stay close.", "Open the door."]


def test_load_srt(tmp_path: Path) -> None:
    f = tmp_path / "s.srt"
    f.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nWhere were you\nwhen the lights went out?\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nStay close.\n",
        encoding="utf-8",
    )
    assert load_lines(f) == ["Where were you\nwhen the lights went out?", "Stay close."]


def test_load_json_and_csv(tmp_path: Path) -> None:
    j = tmp_path / "s.json"
    j.write_text(json.dumps({"intro": ["Hello", "Hi"], "menu": {"start": "New Game", "n": 3}}), encoding="utf-8")
    assert load_lines(j) == ["Hello", "Hi", "New Game"]
    c = tmp_path / "s.csv"
    c.write_text("id,text\n1,Stay close.\n2,Open the door.\n", encoding="utf-8")
    assert load_lines(c) == ["Stay close.", "Open the door."]
    c2 = tmp_path / "plain.csv"
    c2.write_text("Stay close.,x\nOpen the door.,y\n", encoding="utf-8")
    assert load_lines(c2) == ["Stay close.", "Open the door."]


def test_chunked() -> None:
    assert chunked(["a", "b", "c"], 2) == [["a", "b"], ["c"]]
    assert chunked([], 5) == []
    assert chunked(["a", "b"], 0) == [["a"], ["b"]]  # never empty chunks, each a paid request


class StubMessages:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        payload = json.loads(kwargs["messages"][0]["content"])
        body = json.dumps({"items": [t.upper() for t in payload["items"]]})
        return text_response(body, usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def test_chunk_size_below_one_is_refused_on_the_command_line() -> None:
    assert positive_int("1") == 1 and positive_int("50") == 50
    for text, message in (("0", "must be 1 or more"), ("-3", "must be 1 or more"), ("ten", "not a whole number")):
        with pytest.raises(argparse.ArgumentTypeError, match=message):
            positive_int(text)


def test_pretranslate_sync_fills_cache_and_skips_known(tmp_path: Path) -> None:
    client = SimpleNamespace(messages=StubMessages())
    translator = ClaudeTranslator(client=client, source_lang="en")
    cache = TranslationCache(tmp_path / "c.json")
    cache.put("Known line", "tr", "Bilinen")
    lines = ["Known line", "CASEY: Stay close.", "Open the door.", "Alan: Open the door."]
    added = pretranslate_sync(lines, translator, cache, "tr", chunk_size=1)
    assert added == 2
    assert len(client.messages.created) == 2
    assert cache.get("stay close.", "tr") == "STAY CLOSE."  # the words alone, as the overlay looks them up
    assert TranslationCache(tmp_path / "c.json").get("Open the door.", "tr") == "OPEN THE DOOR."
    payload = json.loads(client.messages.created[0]["messages"][0]["content"])
    assert payload == {**payload, "items": ["Stay close."], "speakers": ["CASEY"]}  # the name goes as a hint


class StubBatches:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.status = "in_progress"

    def create(self, requests):
        self.requests = requests
        return SimpleNamespace(id="msgbatch_test", processing_status="in_progress")

    def retrieve(self, batch_id):
        return SimpleNamespace(
            processing_status=self.status,
            request_counts=SimpleNamespace(processing=0, succeeded=len(self.requests)),
        )

    def results(self, batch_id):
        for req in self.requests:
            payload = json.loads(req["params"]["messages"][0]["content"])
            body = json.dumps({"items": ["TR " + t for t in payload["items"]]})
            message = SimpleNamespace(content=[SimpleNamespace(type="text", text=body)])
            yield SimpleNamespace(custom_id=req["custom_id"], result=SimpleNamespace(type="succeeded", message=message))


def test_batch_submit_save_and_collect(tmp_path: Path) -> None:
    batches = StubBatches()
    client = SimpleNamespace(messages=SimpleNamespace(batches=batches))
    translator = ClaudeTranslator(client=client, source_lang="en", game="Fake Game")
    cache = TranslationCache(tmp_path / "c.json")

    requests, chunks = build_batch_requests(["a", "b", "c"], translator, "tr", chunk_size=2)
    assert [r["custom_id"] for r in requests] == ["chunk-00000", "chunk-00001"]
    assert requests[0]["params"]["model"] == "claude-haiku-5-5"
    assert "output_format" not in requests[0]["params"]
    assert chunks["chunk-00001"] == ["c"]

    job = submit_batch(["Stay close.", "Open the door.", "Run!"], translator, cache, "tr", chunk_size=2, client=client)
    assert job is not None and job.batch_id == "msgbatch_test"
    path = tmp_path / "job.json"
    job.save(path)
    loaded = BatchJob.load(path)
    assert loaded.chunks == job.chunks

    ended, added, failed = collect_batch(loaded, cache, client=client)
    assert ended is False and added == 0
    batches.status = "ended"
    ended, added, failed = collect_batch(loaded, cache, client=client)
    assert (ended, added, failed) == (True, 3, 0)
    assert cache.get("Run!", "tr") == "TR Run!"
    assert submit_batch(["Run!"], translator, cache, "tr", client=client) is None  # all cached


def test_a_chunk_whose_reply_lost_an_item_counts_as_failed(tmp_path: Path) -> None:
    """A reply one item short cannot be matched by position: nothing of it
    is cached, rather than every later line under the wrong source."""
    batches = StubBatches()
    client = SimpleNamespace(messages=SimpleNamespace(batches=batches))
    translator = ClaudeTranslator(client=client, source_lang="en")
    cache = TranslationCache(tmp_path / "c.json")
    job = submit_batch(["A", "B", "C"], translator, cache, "tr", chunk_size=3, client=client)
    assert job is not None
    batches.status = "ended"
    short = json.dumps({"items": ["B-cevap", "C-cevap"]})
    message = SimpleNamespace(content=[SimpleNamespace(type="text", text=short)])
    batches.results = lambda batch_id: [
        SimpleNamespace(custom_id="chunk-00000", result=SimpleNamespace(type="succeeded", message=message))
    ]
    assert collect_batch(job, cache, client=client) == (True, 0, 1)
    assert cache.get("A", "tr") is None


def test_batch_goes_through_the_translators_own_client_by_default(tmp_path: Path) -> None:
    """The translator's client carries the app's key (Credential Manager);
    a fresh anthropic.Anthropic() would only see the environment."""
    batches = StubBatches()
    client = SimpleNamespace(messages=SimpleNamespace(batches=batches))
    translator = ClaudeTranslator(client=client, source_lang="en")
    job = submit_batch(["Stay close."], translator, TranslationCache(tmp_path / "c.json"), "tr")
    assert job is not None and [r["custom_id"] for r in batches.requests] == ["chunk-00000"]
