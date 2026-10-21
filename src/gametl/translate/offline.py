"""Offline neural translation with CTranslate2.

Models come from Argos Translate packages (`.argosmodel` zips containing a
CTranslate2 model and a SentencePiece tokenizer), downloaded from the Argos
package index without the argostranslate runtime (which would pull in
PyTorch). Quality is below Claude's, speed is ~50-200 ms per line on CPU,
which makes it the "draft" tier: shown at once, replaced when Claude answers.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Callable

from .base import TranslationRequest

ARGOS_INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


# -- packages --------------------------------------------------------------------


def find_package(index: list[dict], source: str, target: str) -> dict | None:
    """The index entry translating `source` to `target` (ISO codes)."""
    for entry in index:
        if entry.get("from_code") == source and entry.get("to_code") == target and entry.get("links"):
            return entry
    return None


def locate_model_files(root: Path) -> tuple[Path, Path] | None:
    """(CTranslate2 model directory, sentencepiece model) under `root`."""
    model_bins = sorted(root.rglob("model.bin"))
    sp_models = sorted(root.rglob("sentencepiece.model"))
    if not model_bins or not sp_models:
        return None
    return model_bins[0].parent, sp_models[0]


def package_dir(models_dir: Path, source: str, target: str) -> Path:
    return Path(models_dir) / f"argos-{source}_{target}"


def ensure_model(
    source: str,
    target: str,
    models_dir: Path | str,
    progress: Callable[[str], None] | None = None,
) -> tuple[Path, Path]:
    """Return the model files for the pair, downloading the Argos package on
    first use. Raises RuntimeError when no package exists for the pair."""
    import requests

    dest = package_dir(Path(models_dir), source, target)
    found = locate_model_files(dest) if dest.exists() else None
    if found:
        return found

    say = progress or (lambda _s: None)
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
    return found


# -- translator ------------------------------------------------------------------


def split_sentences(line: str) -> list[str]:
    parts = [p for p in _SENTENCE_SPLIT.split(line.strip()) if p]
    return parts or [line]


class OfflineTranslator:
    name = "offline"

    def __init__(
        self,
        model_dir: Path | str,
        sp_model: Path | str,
        compute_type: str = "int8",
        beam_size: int = 2,
        threads: int | None = None,
    ) -> None:
        import ctranslate2
        import sentencepiece as spm

        self.sp = spm.SentencePieceProcessor(model_file=str(sp_model))
        kwargs: dict[str, Any] = {"device": "cpu", "compute_type": compute_type}
        if threads:
            kwargs["intra_threads"] = threads
        self.ct2 = ctranslate2.Translator(str(model_dir), **kwargs)
        self.beam_size = beam_size

    @classmethod
    def from_models_dir(cls, models_dir: Path | str, source: str, target: str, **kwargs: Any) -> "OfflineTranslator":
        found = locate_model_files(package_dir(Path(models_dir), source, target))
        if not found:
            raise RuntimeError(
                f"offline model for {source}->{target} not downloaded; run: gametl --download-model"
            )
        return cls(found[0], found[1], **kwargs)

    @classmethod
    def _from_components(cls, ct2: Any, sp: Any, beam_size: int = 2) -> "OfflineTranslator":
        """For tests: inject stand-ins for the CTranslate2 and SentencePiece objects."""
        self = cls.__new__(cls)
        self.ct2, self.sp, self.beam_size = ct2, sp, beam_size
        return self

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

        tokens = [self.sp.encode(s, out_type=str) for s in sentences]
        results = self.ct2.translate_batch(tokens, beam_size=self.beam_size, max_decoding_length=256)
        translated = [self.sp.decode(r.hypotheses[0]) if r.hypotheses else "" for r in results]

        out: list[str | None] = []
        for lines_plan in plan:
            lines = [" ".join(translated[i] for i in ids) for ids in lines_plan]
            joined = "\n".join(lines).strip()
            out.append(joined or None)
        return out
