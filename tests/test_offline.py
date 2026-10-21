from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gametl.translate.base import TranslationRequest
from gametl.translate.offline import (
    OfflineTranslator,
    find_package,
    locate_model_files,
    package_dir,
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


def test_locate_model_files(tmp_path: Path) -> None:
    assert locate_model_files(tmp_path) is None
    (tmp_path / "pkg" / "model").mkdir(parents=True)
    (tmp_path / "pkg" / "model" / "model.bin").write_bytes(b"")
    (tmp_path / "pkg" / "sentencepiece.model").write_bytes(b"")
    model_dir, sp = locate_model_files(tmp_path)
    assert model_dir == tmp_path / "pkg" / "model"
    assert sp == tmp_path / "pkg" / "sentencepiece.model"
    assert package_dir(tmp_path, "en", "tr") == tmp_path / "argos-en_tr"


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

    def translate_batch(self, tokens, beam_size, max_decoding_length):
        self.batches.append(tokens)
        return [SimpleNamespace(hypotheses=[[t.upper() for t in toks]]) for toks in tokens]


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
