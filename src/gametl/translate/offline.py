"""Offline neural translation with CTranslate2.

Two model sources, both run by the same code:

- OPUS-MT models (e.g. Helsinki-NLP/opus-mt-tc-big-en-tr) converted with
  `scripts/convert_offline_model.py`: a CTranslate2 model plus the model's
  source and target SentencePiece files. Best quality per language pair.
- Argos Translate packages, downloaded from the Argos index without the
  argostranslate runtime (which would pull in PyTorch): a CTranslate2 model
  plus one shared SentencePiece file. Easiest to get, weaker quality.

A converted OPUS model is preferred when both exist for a pair. Quality is
below Claude's; speed is ~20-200 ms per line on CPU, which makes it the
"draft" tier: shown at once, replaced when Claude answers.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import TranslationRequest

ARGOS_INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


@dataclass(slots=True)
class ModelFiles:
    model_dir: Path
    sp_source: Path
    sp_target: Path  # same file as sp_source for Argos packages
    kind: str  # "opus" | "argos"


# -- locating models ---------------------------------------------------------------


def locate_model_files(root: Path) -> ModelFiles | None:
    """Model files under `root`: a CTranslate2 `model.bin` directory plus
    either `source.spm` + `target.spm` (OPUS) or `sentencepiece.model` (Argos)."""
    model_bins = sorted(root.rglob("model.bin"))
    if not model_bins:
        return None
    model_dir = model_bins[0].parent
    source = sorted(root.rglob("source.spm"))
    target = sorted(root.rglob("target.spm"))
    if source and target:
        return ModelFiles(model_dir, source[0], target[0], "opus")
    shared = sorted(root.rglob("sentencepiece.model"))
    if shared:
        return ModelFiles(model_dir, shared[0], shared[0], "argos")
    return None


def opus_dir(models_dir: Path | str, source: str, target: str) -> Path:
    return Path(models_dir) / f"opus-{source}_{target}"


def package_dir(models_dir: Path | str, source: str, target: str) -> Path:
    return Path(models_dir) / f"argos-{source}_{target}"


def find_model(models_dir: Path | str, source: str, target: str) -> ModelFiles | None:
    """The best installed model for the pair: converted OPUS first, then Argos."""
    for candidate in (opus_dir(models_dir, source, target), package_dir(models_dir, source, target)):
        if candidate.exists():
            found = locate_model_files(candidate)
            if found:
                return found
    return None


# -- Argos packages ---------------------------------------------------------------


def find_package(index: list[dict], source: str, target: str) -> dict | None:
    """The index entry translating `source` to `target` (ISO codes)."""
    for entry in index:
        if entry.get("from_code") == source and entry.get("to_code") == target and entry.get("links"):
            return entry
    return None


def quiet(_line: str) -> None:
    """The progress callback that reports nothing."""


def ensure_model(source: str, target: str, models_dir: Path | str, say: Callable[[str], None] = quiet) -> Path:
    """The model folder for the pair, downloading the Argos package on first
    use. Raises RuntimeError when no package exists."""
    import requests

    dest = package_dir(models_dir, source, target)
    found = locate_model_files(dest) if dest.exists() else None
    if found:
        return found.model_dir

    say(f"fetching Argos package index for {source}->{target}")
    index = requests.get(ARGOS_INDEX_URL, timeout=30).json()
    entry = find_package(index, source, target)
    if entry is None:
        raise RuntimeError(f"no offline model package for {source}->{target}")
    url = entry["links"][0]
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "package.argosmodel"
    say(f"downloading {url}")
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with open(archive, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    say(f"downloading offline model: {done * 100 // total}%")
    say("extracting")
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            # Skip the stanza sentence splitter: large and unused here.
            if "/stanza/" in member.filename or member.filename.startswith("stanza/"):
                continue
            zf.extract(member, dest)
    archive.unlink(missing_ok=True)
    found = locate_model_files(dest)
    if not found:
        raise RuntimeError(f"package for {source}->{target} has no model files")
    meta = {"source": source, "target": target, "package": entry.get("code"), "version": entry.get("package_version")}
    (dest / "gametl.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    say("offline model ready")
    return found.model_dir


# -- translator ---------------------------------------------------------------------


def split_sentences(line: str) -> list[str]:
    parts = [p for p in _SENTENCE_SPLIT.split(line.strip()) if p]
    return parts or [line]


class OfflineTranslator:
    name = "offline"

    def __init__(
        self,
        model_dir: Path | str,
        sp_source: Path | str,
        sp_target: Path | str | None = None,
        kind: str = "argos",
        compute_type: str = "int8",
        beam_size: int = 2,
        threads: int | None = None,
    ) -> None:
        import ctranslate2
        import sentencepiece as spm

        self.sp_source = spm.SentencePieceProcessor(model_file=str(sp_source))
        self.sp_target = (
            self.sp_source
            if sp_target is None or Path(sp_target) == Path(sp_source)
            else spm.SentencePieceProcessor(model_file=str(sp_target))
        )
        kwargs: dict[str, Any] = {"device": "cpu", "compute_type": compute_type}
        if threads:
            kwargs["intra_threads"] = threads
        self.ct2 = ctranslate2.Translator(str(model_dir), **kwargs)
        self.beam_size = beam_size
        self.kind = kind
        self.model_dir = Path(model_dir)

    @classmethod
    def from_models_dir(cls, models_dir: Path | str, source: str, target: str, **kwargs: Any) -> OfflineTranslator:
        found = find_model(models_dir, source, target)
        if not found:
            raise RuntimeError(
                f"offline model for {source}->{target} not installed; run: gametl --download-model "
                "(or convert an OPUS-MT model with scripts/convert_offline_model.py)"
            )
        return cls(found.model_dir, found.sp_source, found.sp_target, kind=found.kind, **kwargs)

    @classmethod
    def _from_components(
        cls, ct2: Any, sp: Any, beam_size: int = 2, sp_target: Any = None, kind: str = "argos"
    ) -> OfflineTranslator:
        """For tests: inject stand-ins for the CTranslate2 and SentencePiece objects."""
        self = cls.__new__(cls)
        self.ct2, self.sp_source, self.beam_size, self.kind = ct2, sp, beam_size, kind
        self.sp_target = sp_target or sp
        self.model_dir = Path(".")
        return self

    def _encode(self, sentence: str) -> list[str]:
        tokens = list(self.sp_source.encode(sentence, out_type=str))
        if self.kind == "opus":
            # Marian models are trained with an end-of-sentence token on the
            # source (the HF tokenizer adds it); without it the decoder never
            # stops and repeats until the length limit.
            tokens.append("</s>")
        return tokens

    def translate(self, request: TranslationRequest) -> list[str | None]:
        if not request.texts:
            return []
        # Flatten: text -> lines -> sentences, translate all sentences in one batch.
        plan: list[list[list[int]]] = []  # per text, per line, sentence indices
        sentences: list[str] = []
        for text in request.texts:
            lines_plan: list[list[int]] = []
            for line in text.split("\n"):
                ids: list[int] = []
                for sentence in split_sentences(line):
                    if sentence.strip():
                        ids.append(len(sentences))
                        sentences.append(sentence)
                lines_plan.append(ids)
            plan.append(lines_plan)
        if not sentences:
            return ["" for _ in request.texts]

        tokens = [self._encode(s) for s in sentences]
        results = self.ct2.translate_batch(
            tokens, beam_size=self.beam_size, max_decoding_length=256, no_repeat_ngram_size=3
        )
        translated = [self.sp_target.decode(r.hypotheses[0]) if r.hypotheses else "" for r in results]

        out: list[str | None] = []
        for lines_plan in plan:
            lines = [" ".join(translated[i] for i in ids) for ids in lines_plan]
            joined = "\n".join(lines).strip()
            out.append(joined or None)
        return out
