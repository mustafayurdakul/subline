"""Convert an OPUS-MT model from Hugging Face into the app's offline format.

The conversion needs PyTorch and transformers, which the app itself does
not ship. Run it once in a throwaway environment on top of the project:

  uv run --with torch --with transformers --with huggingface_hub python scripts/convert_offline_model.py --source en --target tr

Default model per pair: Helsinki-NLP/opus-mt-tc-big-<src>-<tgt> (good
quality, ~230M parameters); pass --model to use another Marian model. The
result lands in %APPDATA%\\gametl\\models\\opus-<src>_<tgt> (or --data-dir)
and is preferred over the Argos package from then on.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="source language code, e.g. en")
    p.add_argument("--target", required=True, help="target language code, e.g. tr")
    p.add_argument("--model", help="Hugging Face model id; default Helsinki-NLP/opus-mt-tc-big-<src>-<tgt>")
    p.add_argument("--quantization", default="int8", help="int8 (default), int8_float16, float16, or none")
    p.add_argument("--data-dir", help="app data dir (default %%APPDATA%%\\gametl)")
    p.add_argument("--force", action="store_true", help="overwrite an existing conversion")
    args = p.parse_args()

    from gametl.app.config import ProfileStore
    from gametl.translate.offline import locate_model_files, opus_dir

    model_id = args.model or f"Helsinki-NLP/opus-mt-tc-big-{args.source}-{args.target}"
    dest = opus_dir(ProfileStore(args.data_dir).models_dir, args.source, args.target)
    if dest.exists() and not args.force and locate_model_files(dest):
        print(f"already converted at {dest} (use --force to redo)")
        return 0

    try:
        import ctranslate2
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        print(f"missing {exc.name}; run with: uv run --with torch --with transformers --with huggingface_hub python {sys.argv[0]} ...")
        return 2

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    model_out = dest / "model"
    print(f"converting {model_id} -> {model_out} ({args.quantization})", flush=True)
    converter = ctranslate2.converters.TransformersConverter(model_id)
    converter.convert(str(model_out), quantization=None if args.quantization == "none" else args.quantization, force=True)

    for name in ("source.spm", "target.spm"):
        path = hf_hub_download(model_id, name)
        shutil.copy(path, dest / name)
        print(f"copied {name}")

    (dest / "gametl.json").write_text(
        json.dumps({"source": args.source, "target": args.target, "model": model_id, "quantization": args.quantization}, indent=2),
        encoding="utf-8",
    )
    print(f"offline model ready: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
