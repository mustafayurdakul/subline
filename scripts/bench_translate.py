"""Measure translation request latency per configuration. Makes real API
calls (a few cents at most).

  python scripts/bench_translate.py
  python scripts/bench_translate.py --calls 6 --configs adaptive+structured disabled+plain-json
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

from gametl.app.credentials import anthropic_api_key, has_anthropic_credentials
from gametl.translate.base import TranslationRequest
from gametl.translate.claude import ClaudeTranslator, estimate_cost_usd

TEXTS = [
    "The bridge is gone. We need another way across.",
    "Stay close, and keep your voice down.",
]

CONFIGS: dict[str, dict] = {
    "adaptive+structured": {"thinking": "adaptive", "structured": True},
    "disabled+structured": {"thinking": "disabled", "structured": True},
    "adaptive+plain-json": {"thinking": "adaptive", "structured": False},
    "disabled+plain-json": {"thinking": "disabled", "structured": False},
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="claude-haiku-5-5")
    p.add_argument("--effort", default="low")
    p.add_argument("--calls", type=int, default=4, help="calls per configuration")
    p.add_argument("--configs", nargs="*", default=list(CONFIGS), choices=list(CONFIGS))
    args = p.parse_args()

    if not has_anthropic_credentials():
        print("no Anthropic credentials")
        return 2

    summary: list[tuple[str, list[float], dict[str, int], int]] = []
    for name in args.configs:
        cfg = CONFIGS[name]
        translator = ClaudeTranslator(
            model=args.model,
            effort=args.effort,
            game="Fake Game",
            source_lang="en",
            target_lang="tr",
            api_key=anthropic_api_key(),
            **cfg,
        )
        latencies: list[float] = []
        print(f"== {name} ({args.model}, effort {args.effort})")
        for i in range(args.calls):
            t0 = time.perf_counter()
            try:
                out = translator.translate(TranslationRequest(TEXTS, source_lang="en", target_lang="tr"))
            except Exception as exc:  # report and continue with the next config
                print(f"  call {i + 1}: FAILED {type(exc).__name__}: {exc}")
                break
            ms = (time.perf_counter() - t0) * 1000
            latencies.append(ms)
            u = translator.last_usage
            cache_read = getattr(u, "cache_read_input_tokens", 0)
            cache_write = getattr(u, "cache_creation_input_tokens", 0)
            print(
                f"  call {i + 1}: {ms:6.0f} ms  in={u.input_tokens} out={u.output_tokens} "
                f"cache_read={cache_read} cache_write={cache_write}  -> {out[0][:50]!r}"
            )
        summary.append((name, latencies, dict(translator.usage_totals), translator.calls))

    print("\n== summary (ms)")
    total_cost = 0.0
    for name, lat, totals, calls in summary:
        if not lat:
            print(f"  {name:22s} no successful calls")
            continue
        cost = estimate_cost_usd(args.model, totals) or 0.0
        total_cost += cost
        rest = lat[1:] or lat  # first call pays connection setup and cache write
        print(
            f"  {name:22s} first {lat[0]:5.0f}  then median {statistics.median(rest):5.0f}  "
            f"min {min(rest):5.0f}  max {max(rest):5.0f}  out/call {totals['output'] / calls:.0f} tok"
        )
    print(f"  total cost ~${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
