from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gametl.translate.base import TranslationRequest
from gametl.translate.offline import (
    RUNTIME_PACKAGES,
    OfflineTranslator,
    activate_runtime,
    ensure_runtime,
    find_model,
    find_package,
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


def test_offline_translator_keeps_lines_and_batches_sentences() -> None:
    ct2 = FakeCT2()
    translator = OfflineTranslator._from_components(ct2, FakeSP())
    out = translator.translate(
        TranslationRequest(["Stay close. Keep quiet!\nSecond line", "Another one."], source_lang="en", target_lang="tr")
    )
    assert out == ["STAY CLOSE. KEEP QUIET!\nSECOND LINE", "ANOTHER ONE."]
    assert len(ct2.batches) == 1  # all four sentences in one batch
    assert len(ct2.batches[0]) == 4
    assert translator.translate(TranslationRequest([], target_lang="tr")) == []


def test_missing_model_raises_with_hint(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="download-model"):
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
