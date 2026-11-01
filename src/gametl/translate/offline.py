"""Offline neural translation with CTranslate2.

Two model sources, both run by the same code:

- OPUS-MT models (e.g. Helsinki-NLP/opus-mt-tc-big-en-tr) converted with
  `scripts/convert_offline_model.py`: a CTranslate2 model plus the model's
  source and target SentencePiece files. Best quality per language pair.
- Argos Translate packages, downloaded from the Argos index without the
  argostranslate runtime (which would pull in PyTorch): a CTranslate2 model
  plus one shared SentencePiece file. Easiest to get, weaker quality.

A converted OPUS model is preferred when both exist for a pair. Quality is
below DeepL's and Claude's; speed is ~20-200 ms per line on CPU, which makes
it the "draft" tier: shown at once, replaced when the translator answers.

The libraries (CTranslate2, SentencePiece) are not in the packaged build:
`ensure_runtime` fetches their wheels on the first download and unpacks
them into the data folder, from where `activate_runtime` imports them.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import re
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import TranslationRequest, language_code, quiet, single_line

ARGOS_INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

# The runtime wheels, pinned to the Python the packaged build ships (3.12,
# 64-bit Windows) and checked against these hashes before they are unpacked.
# A development install gets the same packages with `uv sync --extra offline`.
RUNTIME_PACKAGES = ("ctranslate2", "sentencepiece")
RUNTIME_WHEELS = (
    (
        "ctranslate2-4.8.3-cp312-cp312-win_amd64.whl",
        "https://files.pythonhosted.org/packages/db/f8/1aec2aaf0e8a09987085dd2e4a876619fee6026f20ed28a2c2efc6235bec/"
        "ctranslate2-4.8.3-cp312-cp312-win_amd64.whl",
        "b5daf0758d522a422c76e53eb02ce9f42465a9aba938a86b27249fb5db2571b9",
    ),
    (
        "sentencepiece-0.2.2-cp312-cp312-win_amd64.whl",
        "https://files.pythonhosted.org/packages/8d/11/753fca2e6b109be3ab7867abf357dfe48677fe726ae5a5363d0b54ca9450/"
        "sentencepiece-0.2.2-cp312-cp312-win_amd64.whl",
        "7c6e7bf684dc12145bfa685d3060beaea55139134ba848289bee514ed42e7383",
    ),
)


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


def iso_pair(source: str, target: str) -> tuple[str, str]:
    """The pair as ISO 639-1 codes, the names models and packages go by: the
    source is often a rapidocr model name ("japan") or a typed name. A script
    that covers several languages ("cyrillic") stays as it is and finds no model."""
    return language_code(source) or source, language_code(target) or target


def opus_dir(models_dir: Path | str, source: str, target: str) -> Path:
    return Path(models_dir) / f"opus-{source}_{target}"


def package_dir(models_dir: Path | str, source: str, target: str) -> Path:
    return Path(models_dir) / f"argos-{source}_{target}"


def find_model(models_dir: Path | str, source: str, target: str) -> ModelFiles | None:
    """The best installed model for the pair: converted OPUS first, then Argos."""
    source, target = iso_pair(source, target)
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


def _download(url: str, dest: Path, say: Callable[[str], None], what: str) -> None:
    """Stream `url` to `dest`, reporting the progress of `what`."""
    import requests

    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    say(f"downloading {what}: {done * 100 // total}%")


def ensure_model(source: str, target: str, models_dir: Path | str, say: Callable[[str], None] = quiet) -> Path:
    """The model folder for the pair, downloading the Argos package on first
    use. Raises RuntimeError when no package exists."""
    import requests

    source, target = iso_pair(source, target)
    dest = package_dir(models_dir, source, target)
    found = locate_model_files(dest) if dest.exists() else None
    if found:
        return found.model_dir

    say(f"fetching Argos package index for {source}->{target}")
    index = requests.get(ARGOS_INDEX_URL, timeout=30).json()
    entry = find_package(index, source, target)
    if entry is None:
        raise RuntimeError(f"no offline model package for {source}->{target}")
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "package.argosmodel"
    _download(entry["links"][0], archive, say, "the offline model")
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


# -- runtime ----------------------------------------------------------------------------


def activate_runtime(runtime_dir: Path | str) -> None:
    """Put the unpacked runtime, if there is one, on the import path."""
    runtime_dir = Path(runtime_dir)
    if (runtime_dir / RUNTIME_PACKAGES[0]).is_dir() and str(runtime_dir) not in sys.path:
        sys.path.append(str(runtime_dir))


def runtime_available(runtime_dir: Path | str) -> bool:
    """Whether the runtime can be imported: installed with the app, or unpacked under `runtime_dir`."""
    activate_runtime(runtime_dir)
    return all(importlib.util.find_spec(name) is not None for name in RUNTIME_PACKAGES)


def ensure_runtime(runtime_dir: Path | str, say: Callable[[str], None] = quiet) -> None:
    """Make the runtime importable: nothing to do when it is installed,
    else fetch the pinned wheels and unpack them under `runtime_dir`."""
    runtime_dir = Path(runtime_dir)
    if runtime_available(runtime_dir):
        return
    if not (sys.platform == "win32" and sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32):
        raise RuntimeError(
            "the offline runtime download is for the packaged build (64-bit Windows, Python 3.12); "
            "a development install gets it with: uv sync --extra offline"
        )
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for name, url, sha256 in RUNTIME_WHEELS:
        wheel = runtime_dir / name
        _download(url, wheel, say, name)
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != sha256:
            wheel.unlink()
            raise RuntimeError(f"{name} did not match its checksum; try the download again")
        with zipfile.ZipFile(wheel) as zf:
            zf.extractall(runtime_dir)
        wheel.unlink()
    importlib.invalidate_caches()
    if not runtime_available(runtime_dir):
        raise RuntimeError("the offline runtime was unpacked but cannot be imported")
    say("offline runtime ready")


def ensure_offline(
    source: str, target: str, models_dir: Path | str, runtime_dir: Path | str, say: Callable[[str], None] = quiet
) -> Path:
    """Everything the offline translator needs for the pair: the runtime,
    then the model. Returns the model folder."""
    ensure_runtime(runtime_dir, say)
    return ensure_model(source, target, models_dir, say)


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
        try:
            import ctranslate2
            import sentencepiece as spm
        except ImportError as exc:
            raise RuntimeError(
                "offline translation is not installed: press Download on the Translation page "
                "(or run gametl --download-model)"
            ) from exc

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
                f"offline model for {source}->{target} not installed: press Download on the Translation page, "
                "run gametl --download-model, or convert an OPUS-MT model with scripts/convert_offline_model.py"
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
        # Flatten: text -> sentences, translate all sentences in one batch. A
        # text is one paragraph (`single_line`): a sentence wrapped over two
        # OCR lines must reach the model whole.
        plan: list[list[int]] = []  # per text, sentence indices
        sentences: list[str] = []
        for text in request.texts:
            ids: list[int] = []
            for sentence in split_sentences(single_line(text)):
                if sentence.strip():
                    ids.append(len(sentences))
                    sentences.append(sentence)
            plan.append(ids)
        if not sentences:
            return [None] * len(request.texts)

        tokens = [self._encode(s) for s in sentences]
        results = self.ct2.translate_batch(
            tokens, beam_size=self.beam_size, max_decoding_length=256, no_repeat_ngram_size=3
        )
        translated = [self.sp_target.decode(r.hypotheses[0]) if r.hypotheses else "" for r in results]
        return [" ".join(translated[i] for i in ids).strip() or None for ids in plan]
