"""Command: pre-translate a game's script into its translation cache.

gametl-pretranslate script.txt --game "Fake Game"            # Batches API, Opus 5.5, waits up to 10 min
gametl-pretranslate script.srt --game "Fake Game" --sync     # normal API, immediate
gametl-pretranslate --resume JOBFILE                         # collect a batch submitted earlier
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gametl.app.config import ProfileStore, slug
from gametl.app.credentials import anthropic_api_key, has_anthropic_credentials
from gametl.translate.cache import TranslationCache
from gametl.translate.claude import ClaudeTranslator
from gametl.translate.pretranslate import BatchJob, load_lines, pretranslate_sync, submit_batch, wait_for_batch


def say(text: str) -> None:
    print(text, flush=True)


def anthropic_client():
    """An Anthropic client with the key the app knows (Credential Manager
    first, then the environment); the SDK alone would only read the
    environment."""
    import anthropic

    return anthropic.Anthropic(api_key=anthropic_api_key())


def main(argv: list[str] | None = None) -> int:
    from gametl.app.main import utf8_console

    utf8_console()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("script", nargs="?", help="script file: .txt (one line per entry), .srt, .json or .csv")
    p.add_argument("--game", help="game name (must match the one used when running the overlay)")
    p.add_argument("--source-lang", default="en")
    p.add_argument("--target-lang", default="tr")
    p.add_argument("--model", default="claude-opus-5-5", help="quality model by default; batches cost half")
    p.add_argument("--effort", default="low")
    p.add_argument("--glossary", help='JSON file {"term": "translation"}')
    p.add_argument("--tone", help="notes for the translator on tone and formality")
    p.add_argument("--chunk-size", type=int, default=20)
    p.add_argument("--sync", action="store_true", help="use the normal API now instead of a batch")
    p.add_argument("--wait", type=float, default=600.0, help="seconds to wait for the batch (0 = submit and exit)")
    p.add_argument("--resume", metavar="JOBFILE", help="collect results of a batch job saved earlier")
    p.add_argument("--data-dir", help="where caches live (default %%APPDATA%%\\gametl)")
    args = p.parse_args(argv)

    if not args.resume and (not args.script or not args.game):
        p.error("a script file and --game are required (or --resume JOBFILE)")
    if not has_anthropic_credentials():
        say("no Anthropic key: enter one in the app (Settings > Translation) or set ANTHROPIC_API_KEY")
        return 2

    store = ProfileStore(args.data_dir)

    if args.resume:
        job = BatchJob.load(Path(args.resume))
        game = Path(args.resume).stem.split(".")[0]
        cache = TranslationCache(store.cache_dir / f"{game}.{job.target_lang}.claude.json")
        ended, added, failed = wait_for_batch(job, cache, args.wait, client=anthropic_client(), progress=say)
        if not ended:
            say("batch still running; run --resume again later")
            return 3
        say(f"collected {added} lines ({failed} chunks failed); cache now {len(cache)} entries")
        return 0

    glossary = json.loads(Path(args.glossary).read_text(encoding="utf-8")) if args.glossary else None
    lines = load_lines(args.script)
    cache_path = store.cache_dir / f"{slug(args.game)}.{args.target_lang}.claude.json"
    cache = TranslationCache(cache_path)
    translator = ClaudeTranslator(
        model=args.model,
        effort=args.effort,
        game=args.game,
        glossary=glossary,
        tone=args.tone,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        api_key=anthropic_api_key(),
    )
    say(f"{len(lines)} lines from {args.script}; cache {cache_path} ({len(cache)} entries)")

    if args.sync:
        added = pretranslate_sync(lines, translator, cache, args.target_lang, args.chunk_size, say)
        totals = translator.usage_totals
        say(f"added {added} lines; tokens {totals['input']} in / {totals['output']} out over {translator.calls} calls")
        return 0

    client = translator._client  # carries the app's key; the batch calls reuse it
    job = submit_batch(lines, translator, cache, args.target_lang, args.chunk_size, client=client)
    if job is None:
        say("every line is already in the cache")
        return 0
    job_path = store.root / "pretranslate" / f"{slug(args.game)}.{job.batch_id}.json"
    job.save(job_path)
    say(f"batch {job.batch_id} submitted with {len(job.chunks)} chunks; job saved to {job_path}")
    if args.wait <= 0:
        say(f'collect later with: gametl-pretranslate --resume "{job_path}"')
        return 0
    ended, added, failed = wait_for_batch(job, cache, args.wait, client=client, progress=say)
    if not ended:
        say(f'still running after {args.wait:.0f}s; collect later with: gametl-pretranslate --resume "{job_path}"')
        return 3
    say(f"collected {added} lines ({failed} chunks failed); cache now {len(cache)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
