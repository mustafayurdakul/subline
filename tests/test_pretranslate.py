from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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


class StubMessages:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        payload = json.loads(kwargs["messages"][0]["content"])
        body = json.dumps({"items": [t.upper() for t in payload["items"]]})
        return SimpleNamespace(
            stop_reason="end_turn",
            stop_details=None,
            content=[SimpleNamespace(type="text", text=body)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_pretranslate_sync_fills_cache_and_skips_known(tmp_path: Path) -> None:
    client = SimpleNamespace(messages=StubMessages())
    translator = ClaudeTranslator(client=client, source_lang="en", target_lang="tr")
    cache = TranslationCache(tmp_path / "c.json")
    cache.put("Known line", "tr", "Bilinen")
    added = pretranslate_sync(["Known line", "Stay close.", "Open the door."], translator, cache, "tr", chunk_size=1)
    assert added == 2
    assert len(client.messages.created) == 2
    assert cache.get("stay close.", "tr") == "STAY CLOSE."
    assert TranslationCache(tmp_path / "c.json").get("Open the door.", "tr") == "OPEN THE DOOR."


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
    translator = ClaudeTranslator(client=client, source_lang="en", target_lang="tr", game="Fake Game")
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

    ended, added, failed = collect_batch(loaded, translator, cache, client=client)
    assert ended is False and added == 0
    batches.status = "ended"
    ended, added, failed = collect_batch(loaded, translator, cache, client=client)
    assert (ended, added, failed) == (True, 3, 0)
    assert cache.get("Run!", "tr") == "TR Run!"
    assert submit_batch(["Run!"], translator, cache, "tr", client=client) is None  # all cached
