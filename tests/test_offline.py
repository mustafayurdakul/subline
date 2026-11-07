from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from gametl.translate.base import TranslationRequest
from gametl.translate.offline import (
    ARGOS_INDEX_URL,
    RUNTIME_PACKAGES,
    DownloadCancelled,
    OfflineTranslator,
    activate_runtime,
    ensure_model,
    ensure_runtime,
    find_model,
    find_package,
    iso_pair,
    locate_model_files,
    opus_dir,
    package_dir,
    runtime_available,
    split_sentences,
)


def test_find_package_matches_pair_with_links() -> None:
    index = [
        {"from_code": "en", "to_code": "de", "links": ["x"]},
        {"from_code": "en", "to_code": "tr", "links": []},
        {"from_code": "en", "to_code": "tr", "links": ["https://example/en_tr.argosmodel"], "code": "translate-en_tr"},
    ]
    assert find_package(index, "en", "tr")["code"] == "translate-en_tr"
    assert find_package(index, "tr", "en") is None


def _make_argos(root: Path) -> None:
    (root / "pkg" / "model").mkdir(parents=True)
    (root / "pkg" / "model" / "model.bin").write_bytes(b"")
    (root / "pkg" / "sentencepiece.model").write_bytes(b"")


def _make_opus(root: Path) -> None:
    (root / "model").mkdir(parents=True)
    (root / "model" / "model.bin").write_bytes(b"")
    (root / "source.spm").write_bytes(b"")
    (root / "target.spm").write_bytes(b"")


def test_locate_model_files_argos_and_opus(tmp_path: Path) -> None:
    assert locate_model_files(tmp_path) is None
    argos = tmp_path / "a"
    _make_argos(argos)
    found = locate_model_files(argos)
    assert found.kind == "argos"
    assert found.model_dir == argos / "pkg" / "model"
    assert found.sp_source == found.sp_target == argos / "pkg" / "sentencepiece.model"

    opus = tmp_path / "o"
    _make_opus(opus)
    found = locate_model_files(opus)
    assert found.kind == "opus"
    assert found.sp_source == opus / "source.spm" and found.sp_target == opus / "target.spm"


def test_find_model_prefers_converted_opus(tmp_path: Path) -> None:
    assert find_model(tmp_path, "en", "tr") is None
    _make_argos(package_dir(tmp_path, "en", "tr"))
    assert find_model(tmp_path, "en", "tr").kind == "argos"
    _make_opus(opus_dir(tmp_path, "en", "tr"))
    assert find_model(tmp_path, "en", "tr").kind == "opus"


def test_ocr_model_names_and_typed_names_find_the_iso_named_model(tmp_path: Path) -> None:
    assert iso_pair("japan", "tr") == ("ja", "tr")
    assert iso_pair("German", "tr") == ("de", "tr")
    assert iso_pair("cyrillic", "tr") == ("cyrillic", "tr")  # no one language: no model
    _make_argos(package_dir(tmp_path, "ja", "tr"))
    assert find_model(tmp_path, "japan", "tr").kind == "argos"


def test_split_sentences() -> None:
    assert split_sentences("Stay close. Keep your voice down!") == ["Stay close.", "Keep your voice down!"]
    assert split_sentences("No punctuation here") == ["No punctuation here"]
    assert split_sentences("") == [""]


class FakeSP:
    def encode(self, text: str, out_type=str) -> list[str]:
        return text.split()

    def decode(self, tokens: list[str]) -> str:
        return " ".join(tokens)


class FakeCT2:
    def __init__(self) -> None:
        self.batches: list[list[list[str]]] = []

    def translate_batch(self, tokens, beam_size, max_decoding_length, no_repeat_ngram_size=0):
        self.batches.append(tokens)
        return [SimpleNamespace(hypotheses=[[t.upper() for t in toks if t != "</s>"]]) for toks in tokens]


def test_opus_models_get_the_end_of_sentence_token() -> None:
    ct2 = FakeCT2()
    translator = OfflineTranslator._from_components(ct2, FakeSP(), kind="opus")
    assert translator.translate(TranslationRequest(["New Game"], target_lang="tr")) == ["NEW GAME"]
    assert ct2.batches[0] == [["New", "Game", "</s>"]]
    argos = OfflineTranslator._from_components(FakeCT2(), FakeSP(), kind="argos")
    argos.translate(TranslationRequest(["New Game"], target_lang="tr"))
    assert argos.ct2.batches[0] == [["New", "Game"]]


def test_offline_translator_batches_sentences() -> None:
    ct2 = FakeCT2()
    translator = OfflineTranslator._from_components(ct2, FakeSP())
    out = translator.translate(
        TranslationRequest(["Stay close. Keep quiet!\nSecond line", "Another one."], source_lang="en", target_lang="tr")
    )
    assert out == ["STAY CLOSE. KEEP QUIET! SECOND LINE", "ANOTHER ONE."]
    assert len(ct2.batches) == 1  # all four sentences in one batch
    assert len(ct2.batches[0]) == 4
    assert translator.translate(TranslationRequest([], target_lang="tr")) == []


def test_a_sentence_wrapped_over_two_lines_is_translated_whole() -> None:
    ct2 = FakeCT2()
    translator = OfflineTranslator._from_components(ct2, FakeSP())
    out = translator.translate(TranslationRequest(["Where were you\nwhen the lights went out?"], target_lang="tr"))
    assert ct2.batches[0] == [["Where", "were", "you", "when", "the", "lights", "went", "out?"]]  # one sentence
    assert out == ["WHERE WERE YOU WHEN THE LIGHTS WENT OUT?"]


def test_missing_model_raises_with_hint(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="gametl-cli --download-model"):
        OfflineTranslator.from_models_dir(tmp_path, "en", "tr")


def test_an_unpacked_runtime_goes_on_the_import_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setattr(sys, "path", list(sys.path))
    activate_runtime(tmp_path)
    assert str(tmp_path) not in sys.path  # nothing unpacked there yet
    for name in RUNTIME_PACKAGES:
        (tmp_path / name).mkdir()
        (tmp_path / name / "__init__.py").write_text("")
    assert runtime_available(tmp_path)
    assert sys.path.count(str(tmp_path)) == 1
    activate_runtime(tmp_path)
    assert sys.path.count(str(tmp_path)) == 1  # once


def test_the_runtime_download_is_for_the_packaged_build_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import gametl.translate.offline as offline

    monkeypatch.setattr(offline, "runtime_available", lambda runtime_dir: False)
    monkeypatch.setattr(offline.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="uv sync --extra offline"):
        ensure_runtime(tmp_path)
    assert not tmp_path.exists() or not any(tmp_path.iterdir())  # nothing fetched


def test_a_wheel_that_fails_its_checksum_is_deleted_not_unpacked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The checksum is the only guard before downloaded code goes on the import path."""
    import gametl.translate.offline as offline

    monkeypatch.setattr(offline, "runtime_available", lambda runtime_dir: False)
    monkeypatch.setattr(offline, "sys", SimpleNamespace(platform="win32", version_info=(3, 12, 0), maxsize=2**63 - 1))
    monkeypatch.setattr(offline, "_download", lambda url, dest, say, what, cancelled: dest.write_bytes(b"tampered"))
    with pytest.raises(RuntimeError, match="checksum"):
        ensure_runtime(tmp_path / "runtime")
    assert list(tmp_path.iterdir()) == []  # neither the runtime folder nor its staging folder


def _argos_archive(with_model: bool = True) -> bytes:
    """An Argos package as the index links it: a zip of one folder."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        if with_model:
            zf.writestr("translate-en_tr/model/model.bin", b"weights")
        zf.writestr("translate-en_tr/sentencepiece.model", b"vocab")
        zf.writestr("translate-en_tr/stanza/tokenize.pt", b"unused")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, body: bytes = b"", data=None, status: int = 200) -> None:
        self.body, self.data, self.status = body, data, status
        self.headers = {"content-length": str(len(body))}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def raise_for_status(self) -> None:
        import requests

        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} Server Error")

    def json(self):
        return self.data

    def iter_content(self, chunk_size: int):
        for i in range(0, len(self.body), 4):  # small chunks: a cancel can land between them
            yield self.body[i : i + 4]


def _serve(monkeypatch: pytest.MonkeyPatch, archive: bytes, index_status: int = 200) -> list[str]:
    """Answer the index and package URLs; returns the URLs asked for."""
    import requests

    asked: list[str] = []
    index = [{"from_code": "en", "to_code": "tr", "links": ["https://example/en_tr.argosmodel"], "code": "en_tr"}]

    def get(url: str, **_kwargs) -> FakeResponse:
        asked.append(url)
        if url == ARGOS_INDEX_URL:
            return FakeResponse(data=index, status=index_status)
        return FakeResponse(body=archive)

    monkeypatch.setattr(requests, "get", get)
    return asked


def test_a_downloaded_package_is_moved_into_place_only_when_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, _argos_archive())
    model_dir = ensure_model("en", "tr", tmp_path)
    dest = package_dir(tmp_path, "en", "tr")
    assert model_dir == dest / "translate-en_tr" / "model"
    assert json.loads((dest / "gametl.json").read_text(encoding="utf-8"))["package"] == "en_tr"
    assert not (dest / "package.argosmodel").exists() and not (dest / "translate-en_tr" / "stanza").exists()
    assert [p.name for p in tmp_path.iterdir()] == [dest.name]  # no staging folder left

    # A package without model files leaves nothing behind, and no installed model.
    other = tmp_path / "other"
    _serve(monkeypatch, _argos_archive(with_model=False))
    with pytest.raises(RuntimeError, match="no model files"):
        ensure_model("en", "tr", other)
    assert list(other.iterdir()) == []


def test_a_cancelled_or_failed_download_leaves_nothing_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _argos_archive())
    chunks = iter(range(1000))
    with pytest.raises(DownloadCancelled):
        ensure_model("en", "tr", tmp_path, cancelled=lambda: next(chunks) >= 3)  # mid-download
    assert list(tmp_path.iterdir()) == []

    import requests

    _serve(monkeypatch, _argos_archive(), index_status=503)
    with pytest.raises(requests.HTTPError, match="503"):  # the server's answer, not a JSON error
        ensure_model("en", "tr", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_folder_cut_short_is_fetched_again_and_an_opus_model_is_used_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _serve(monkeypatch, _argos_archive())
    _make_argos(package_dir(tmp_path, "en", "tr"))  # model files, but no gametl.json: extraction was cut short
    ensure_model("en", "tr", tmp_path)
    assert asked and (package_dir(tmp_path, "en", "tr") / "gametl.json").exists()

    asked.clear()
    assert ensure_model("en", "tr", tmp_path) == package_dir(tmp_path, "en", "tr") / "translate-en_tr" / "model"
    _make_opus(opus_dir(tmp_path, "de", "tr"))
    assert ensure_model("German", "tr", tmp_path) == opus_dir(tmp_path, "de", "tr") / "model"
    assert asked == []  # installed models: nothing fetched
