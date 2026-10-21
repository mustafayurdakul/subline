# Real-time In-Game Translation Overlay - Design Plan

Status: draft v0.2 (2026-10-21). Nothing built yet; this is the plan to agree on first.

Settled so far: Python 3.12 + PySide6 (see 4.1); Claude Haiku 5.5 as the
default translator with Opus 5.5 as the quality option (see 4.4); patch as the
default overlay style (see 4.5); a delay of about half a second before a
never-seen line shows its translation is acceptable for v1 (see 2.1).

Language pair for v1: English source, Turkish target (settled 2026-10-21).
First test game still to be named; `scripts/fake_game.py` stands in.

## 1. Goal

A Windows desktop app that watches a running game, reads any on-screen text
(subtitles, dialogue boxes, menus, signs), translates it into the user's language
with an AI model, and draws the translation on top of the game at the same
position, so the game reads as if it were localized.

Works with any game, because it only looks at pixels: no game files are
modified, nothing is injected into the game process.

Non-goals for v1: exclusive-fullscreen games (see 5.7), vertical CJK text,
audio/voice translation, editing game files.

## 2. How it works (pipeline)

```
Capture -> Diff -> OCR -> Group/Track -> Stabilize -> Translate (cached) -> Layout -> Overlay
```

1. **Capture** the game window as frames (BGRA) at ~5-10 Hz.
2. **Diff**: skip the frame if nothing changed (most frames).
3. **OCR**: detect text regions, recognize each line -> text + box + confidence.
4. **Group / track**: merge lines into blocks (a subtitle, a dialogue box);
   match blocks to the previous frame's blocks by overlap so each block keeps an id.
5. **Stabilize**: a block is "ready" once its text has stopped changing for
   N frames (handles typewriter effects). Translate once, not every frame.
6. **Translate**: exact and fuzzy cache lookup first; otherwise batch the
   ready blocks into one model request with game context and a glossary.
7. **Layout**: fit the translation into the source box (shrink font, wrap),
   pick a background and text colour from the source pixels.
8. **Overlay**: a transparent, click-through, always-on-top window glued to the
   game window draws the blocks; removes them when the source text disappears.

Estimated latency budget (to be measured in M0):

| Stage                              | Typical            |
| ---------------------------------- | ------------------ |
| Capture (WGC)                      | 2-5 ms             |
| Frame diff                         | < 1 ms             |
| Text detection (CPU, 960 px wide)  | 30-80 ms           |
| Recognition (CPU, per line)        | 5-15 ms            |
| Stability wait                     | 200-400 ms         |
| Translation, model call            | 0.4-1.5 s          |
| Translation, cache hit             | ~0 ms              |
| Layout + render                    | < 5 ms             |

New line end to end: roughly 0.7-2 s. Repeated or cached line: ~0.3 s.
Subtitles usually stay up for 2 s or more, so this is acceptable; menus become
instant after the first sighting because of the cache.

Measured in M0 on this machine (section 9): a subtitle strip OCRs in ~40 ms
and a full 1282x752 frame in ~140 ms on CPU, inside the estimates above.

### 2.1 Latency strategy (agreed target)

Target for v1: a never-seen subtitle shows its translation within about
0.5-0.8 s of appearing; a line seen before, or pre-translated, within about
0.2 s. The original can never be replaced at the same instant it appears,
because the app only learns the text once the game has drawn it.

Expected delay after a subtitle appears, by setup (to be measured in M0):

| Setup                                 | New line  |
| ------------------------------------- | --------- |
| Claude Haiku 5.5, low effort          | 0.5-0.8 s |
| Claude Opus 5.5, low effort           | 1-1.5 s   |
| Local neural translation on CPU       | 0.2-0.3 s |
| Line seen before (cache hit)          | ~0.2 s    |
| Script pre-translated from game files | ~0.2 s    |

Built into the default path:

- **Subtitle zone at high rate.** OCR only the subtitle region (user-drawn or
  auto-detected) at 10 Hz; scan the full frame for other text at 1-2 Hz.
- **One confirming frame.** A subtitle that appears whole is translated after a
  single confirming frame (100 ms). The longer stability wait applies only
  while the text is still growing (typewriter effect).
- **Lean model calls.** Default model is Haiku 5.5 at low effort; one warm HTTP
  connection reused across calls; system prompt and glossary prompt-cached;
  small output limit; structured JSON output; several ready blocks per call.
- **Cache first.** Exact and fuzzy match on normalised text, persisted per
  game, so every repeated line is instant.

Optional fast paths (built in M5):

- **A. Fast-first, then refine.** Show a local neural translation (CTranslate2
  running OPUS-MT or NLLB) in ~0.2-0.3 s, then swap in the Claude translation
  when it arrives. Off by default because the text visibly changes once; the
  swap is skipped when the two are near-identical or the subtitle is about to
  disappear.
- **B. Pre-translated script.** For games whose subtitles can be extracted as
  text (plain lines, CSV, JSON, SRT, Unity or Unreal localisation exports),
  import the file, translate it once with Opus 5.5 through the Message Batches
  API (half price, no latency pressure), and store the result as a per-game
  table. At runtime OCR output is fuzzy-matched against the table; a hit
  renders at once, a miss falls back to the live path. Best quality and lowest
  latency, at the cost of a per-game setup step. Extracting the file from the
  game's archives is the user's job, since the tools differ per game.
- **C. Predictive hiding (experimental).** When a known subtitle zone changes,
  patch over the original immediately and fill in the translation when it
  arrives, so the source language is never read. Off by default; flicker risk.

Typewriter dialogue boxes wait for the typing to finish in v1; progressive
translation of partial text is a later improvement.

## 3. Architecture (modules)

Each module sits behind a small interface so backends can be swapped.

| Module       | Responsibility                                                                 |
| ------------ | ------------------------------------------------------------------------------ |
| `capture/`   | Window-targeted screen capture; yields frames + the window's screen rect.      |
| `ocr/`       | `TextDetector` + `TextRecognizer`. Backends: RapidOCR (default), Windows OCR.  |
| `tracking/`  | Line -> block grouping, cross-frame matching, stability gate, hysteresis.      |
| `translate/` | `Translator` interface; Claude backend (default), offline NMT later; cache; batching queue. |
| `layout/`    | Font-size search, wrapping, background/text colour sampling, collision avoidance. |
| `overlay/`   | Transparent click-through window that tracks the game; renders blocks.         |
| `app/`       | Tray icon, settings window, window picker, hotkeys, per-game profiles, config. |

Threading: capture + OCR on a worker thread; translation calls async on a
thread pool; overlay on the UI thread, fed by a queue of render commands.
The UI thread never waits on OCR or the network.

## 4. Key decisions (recommended defaults)

### 4.1 Stack: Python 3.12 + PySide6 (settled for v1)

Why: the OCR/ML tooling is Python-first (RapidOCR, ONNX Runtime, OpenCV), so
iterating on the hard parts (OCR quality, stabilization, layout) is fastest.
PySide6 gives a translucent frameless overlay window and correct text shaping
for every script, including right-to-left. Packaged with PyInstaller.

Alternative (not chosen): C# .NET 8 + WPF. Better for a polished single-exe
product and has first-class access to Windows Graphics Capture and
Windows.Media.Ocr, but OCR tuning is slower. A sensible port target once the
pipeline is proven in Python.

Environment check (2026-10-21): this machine has only Python 3.15.0, which is
too new for the compiled packages. A dry-run resolve showed onnxruntime has
no 3.15 wheel and PySide6 6.11 declares `<3.15`. M0 therefore starts by
installing Python 3.12 side by side. Preferred: `uv` (no admin rights needed):

```
pip install uv
uv python install 3.12
uv venv --python 3.12
```

Alternative: `winget install Python.Python.3.12`, then `py -3.12 -m venv .venv`.

### 4.2 Capture: Windows Graphics Capture (WGC), window-targeted

- `windows-capture` (Rust-backed WGC bindings for Python): captures a specific
  window, works for borderless/windowed games, DPI-correct, and captures only
  that window's content, so our overlay is never fed back into OCR.
- Alternative: Desktop Duplication (`dxcam` / `bettercam`). Monitor-level, fast,
  but captures our overlay too unless the overlay sets
  `WDA_EXCLUDEFROMCAPTURE`. Keep as a fallback.
- Exclusive fullscreen bypasses the compositor; no overlay can draw over it
  without DirectX injection. We require borderless windowed mode and say so in
  the UI (nearly every modern game supports it).

### 4.3 OCR: RapidOCR with PP-OCRv6 models on ONNX Runtime

- Detection (DBNet) + recognition (SVTR). rapidocr 3.10 ships PP-OCRv6 as one
  multilingual det + rec model per size (tiny / small / medium) covering
  Chinese, Japanese, English and most Latin-script languages. Korean, Cyrillic,
  Arabic, Thai, Greek and Devanagari sources use the per-script PP-OCRv5
  mobile recognisers instead. Default: PP-OCRv6 small (measured in section 9).
- CPU by default, restricted to changed regions and user-defined zones.
  Optional GPU via `onnxruntime-directml` (works on any vendor), opt-in because
  the game is already using the GPU.
- Zero-install fallback: Windows.Media.Ocr (built into Windows; needs the
  language pack installed; weaker on stylised fonts).
- Preprocessing for game fonts: 2x upscale of small text, contrast stretch,
  optional inversion for light-on-dark text.
- Later "accuracy mode": send low-confidence crops to a vision-capable Claude
  model to read them.

### 4.4 Translation: Claude via the Anthropic Python SDK (pluggable)

- Model: `claude-haiku-5-5` by default (settled: it meets the real-time
  target in 2.1); `claude-opus-5-5` offered as the "quality" setting, which
  adds roughly half a second per new line. Effort set to `low` for latency.
  Script pre-translation (2.1, path B) always uses Opus, since it runs ahead
  of time through the Batches API with no latency pressure.
- One request per batch of ready blocks, using structured output (JSON in,
  JSON out) so several blocks translate in one round trip.
- Prompt contents: target language, game title/genre, user glossary (names,
  terms, tone), the last ~10 translated lines as context, and an instruction
  to keep translations about as short as the source so they fit the box.
  System prompt + glossary are prompt-cached.
- Cost sanity: a typical request is about 400 input + 60 output tokens.
  Haiku 5.5: ~$0.00007 per request. Opus 5.5: ~$0.003 per request. An hour of
  dialogue-heavy play is a few hundred requests.
- Cache: exact match on normalised text, plus fuzzy match (small edit distance)
  so OCR noise does not cause retranslation of the same line. Persisted per
  game on disk.
- Offline backend later: CTranslate2 running OPUS-MT or NLLB-200.
- Other online backends (DeepL, Google) fit the same interface.

### 4.5 Overlay rendering

- PySide6 window: frameless, stays on top, tool window (no taskbar entry),
  transparent for input (clicks go to the game), translucent background.
- Follows the game window: poll the window's extended frame bounds and client
  rect at ~30 Hz (or hook move/size events); hides when the game is not in
  the foreground.
- Per-Monitor V2 DPI awareness so OCR pixel coordinates map 1:1 onto the
  overlay.
- Box styles (user choice; patch is the settled default):
  - patch (default): opaque fill sampled from the source background, so the
    original text disappears and the translation sits in its place. Sampling:
    median colour of the box border pixels, falling back to the dominant
    non-text colour inside the box; text colour taken from the high-contrast
    pixels inside the box;
  - pill: semi-transparent dark rounded rectangle, original still faintly visible;
  - outline: text with a dark outline, no box.
- Fonts: bundle Noto Sans plus CJK / Arabic / Devanagari variants; user can
  override.

## 5. Hard problems and the plan for each

1. **Typewriter / progressively revealed text.** Stability gate ("unchanged
   for N frames") plus a "text stopped growing" heuristic. Translate once.
2. **Flicker.** Track blocks by overlap across frames; keep a block on screen
   for a few frames after the source vanishes (hysteresis); snap coordinates
   to whole pixels.
3. **Translation longer than the source.** Font-size search down to a floor,
   then wrap, then let the box grow downward, never over other detected text.
4. **Stylised / outlined fonts.** Preprocessing, the larger PP-OCRv5 model,
   per-game OCR profiles, vision-model fallback for low-confidence crops.
5. **Text that should not be translated.** HUD numbers, minimap, text already
   in the target language. Language detection + skip rule, plus user-drawn
   ignore zones.
6. **FPS impact on the game.** CPU OCR, region limits, frame-diff skipping,
   OCR rate cap (default 5 Hz), everything off the UI thread.
7. **Exclusive fullscreen.** Not supported in v1; detect it and tell the user
   to switch to borderless.
8. **Feedback loop (reading our own overlay).** Window-targeted capture avoids
   it; additionally mark the overlay as excluded from capture.
9. **Anti-cheat.** No injection, no hooks, no memory reads; capture and overlay
   only, which is the same category as streaming software. Documented, not
   blocked.

## 6. Milestones

| #  | Milestone          | Scope                                                                                         | Est.     |
| -- | ------------------ | --------------------------------------------------------------------------------------------- | -------- |
| M0 | Spike (done 2026-10-21) | Python 3.12 via uv, project skeleton, WGC capture + RapidOCR with timings, fake game window for testing. Results in section 9. | done     |
| M1 | Overlay MVP (done 2026-10-21) | Click-through overlay following the window, block tracker with confirmation and hysteresis, patch rendering with sampled colours, dummy translator, CLI entry point. Results in section 10. | done     |
| M2 | Real translation (built 2026-10-21, live run pending) | Claude backend with structured output, asynchronous service, three-tier cache, context window, CLI options. Results in section 11. | built    |
| M3 | Layout quality (done 2026-10-21) | Wrap/shrink/grow fitter, busy-background detection with pill fallback, jitter smoothing, ignore zones and patterns. Results in section 12. | done     |
| M4 | App shell (done 2026-10-21) | Tray icon, settings window with window picker, global hotkeys, per-game profiles in %APPDATA%, controller shared with the CLI. Results in section 13. | done     |
| M5 | Fast paths (done 2026-10-21) | Offline CTranslate2 backend from Argos packages, draft-then-refine tier, script import with sync or Batches API pre-translation into the cache. Results in section 14. | done     |
| M6 | Packaging (done 2026-10-21) | PyInstaller one-folder build with tray and console executables, models downloaded on first run, log file for the windowed app. Results in section 15. | done     |
| M7 | Extras             | DirectML option, glossary editor, predictive hiding (experimental), leaner reply format, high-DPI and multi-monitor checks, a real game. | open     |

Testing: a folder of real game screenshots (varied fonts and languages) with
expected text as an OCR benchmark; unit tests for the cache, the stabilizer and
layout fitting; a manual QA checklist (DPI 100/125/150 %, multi-monitor, window
move/resize, alt-tab, borderless vs exclusive).

## 7. Decisions needed

1. First target game for testing on real rendering (the fake game covers the
   pipeline but not real fonts, effects or frame rates).

Settled:

- Language pair: English to Turkish first. OCR model: PP-OCRv6 small, lang
  `en`. Turkish is Latin-script, so the bundled UI font covers it; Turkish
  translations run longer than English, which M3's wrapping must absorb
  (2026-10-21).

- Default overlay style: patch, hiding the original under a sampled
  background; pill and outline stay as options (2026-10-21).

- Stack: Python 3.12 + PySide6 for v1 (2026-10-21).
- Default translation model: Claude Haiku 5.5; Opus 5.5 kept as the quality
  option. Offline NMT follows in M5 (2026-10-21).
- Latency: about half a second for a never-seen line is acceptable for v1;
  the fast paths in 2.1 are planned as M5 (2026-10-21).

## 8. Prior art worth a look

- YomiNinja: Electron + PaddleOCR, in-place overlay, Japanese-focused.
- Translumo: C#, Windows OCR / Tesseract / EasyOCR, shows text in a separate panel.
- MORT: C#, in-place overlay.
- XUnity.AutoTranslator: for Unity games only, replaces text inside the engine.
  Better than OCR when it applies; worth mentioning to users as the preferred
  path for Unity titles.

## 9. M0 results (2026-10-21)

Setup: this machine, CPU only, PP-OCRv6 small, English, capture capped at
10 Hz. Target: `scripts/fake_game.py` (1280x720 client area, 1282x752 window
including the title bar) showing a HUD line and a bold 26 pt subtitle.

| Measurement                               | Value                                   |
| ----------------------------------------- | --------------------------------------- |
| Capture interval (cap 10 Hz)              | median 101 ms (~9.9 fps)                |
| Full-frame OCR, 1282x752, 3-4 lines       | det ~65 ms, rec ~70 ms, total ~140 ms   |
| Subtitle strip OCR, 1282x188, 1 line      | det ~20 ms, rec ~24 ms, total ~40 ms    |
| First OCR call after start                | +150-300 ms once (now absorbed by warm-up) |
| Engine init incl. model load              | ~1.1 s                                  |
| Model download (first run only)           | ~20 s                                   |
| Recognition on the fake subtitle          | exact text, confidence 0.99-1.00        |

Findings:

- A WGC frame has the size of the DWM extended frame bounds (title bar
  included for a normal window); frame pixel (x, y) is at screen position
  (left + x, top + y). For borderless games the client area and the frame
  coincide. Confirmed by overlaying boxes on saved frames.
- Frame-diff skipping on a 1/8-scale grey thumbnail skipped 49 of 57 frames
  against a slowly moving background; a subtitle change registered as diff 3
  (full frame) and 6.6 (strip) with a 1.0 threshold. Real games move more, so
  per-block change detection comes with tracking in M1.
- A strip at ~40 ms per OCR leaves the whole 0.5-0.8 s budget to the
  confirming frame and the model call. Full-frame scans at ~140 ms fit the
  planned 1-2 Hz sweep for non-subtitle text.
- rapidocr's default detector upscales any image whose short side is under
  736 px; the wrapper caps the long side at 960 instead (standard PaddleOCR),
  which is what makes the strip cheap.
- Environment: Python 3.15 is unusable for this stack; the uv-managed 3.12.15
  works. The venv had to go to a short path (`~/.venvs/gametl` through
  `UV_PROJECT_ENVIRONMENT`, see `scripts/env.ps1`) because inside the
  session folder some package files exceed the 260-character Windows path
  limit and fail to import. Moving the project to a short path such as
  `C:\code\gametl` removes the need for the workaround.
- Versions: windows-capture 2.0.1, rapidocr 3.10.0, onnxruntime 1.31.0,
  opencv 5.0.0, PySide6 6.12.0, numpy 2.5.4, Python 3.12.15.

Decisions taken: OCR engine for v1 is RapidOCR PP-OCRv6 small on CPU, subtitle
zone at 10 Hz, full frame at 1-2 Hz. DirectML GPU stays opt-in and untested.
GPU and server-size models can be revisited if a real game's fonts need them.

## 10. M1 results (2026-10-21)

What runs: `uv run gametl --window "<title>"` opens a transparent,
click-through, always-on-top overlay over the target window, OCRs its client
area on a worker thread, tracks text blocks across frames, and patches each
stable block with the upper-cased text in the sampled background and text
colours. Verified against `scripts/fake_game.py` with a screenshot taken
through the overlay: subtitle, HUD and title patched in place, block ids stable
across 44 frames, 28 tests passing (native window styles included).

Design points settled while building it:

- **Coordinates.** The app disables Qt's high-DPI scaling and sets
  Per-Monitor-V2 awareness, so overlay pixels equal capture pixels and a block
  is drawn at its OCR box with no conversion. Untested so far at 125 % / 150 %
  display scaling (this machine runs 100 %).
- **Native styles.** Besides the Qt flags, the overlay forces the Win32
  extended styles (transparent, layered, no-activate, tool window) and asks
  to be excluded from screen capture; a test checks the styles.
- **Change confirmation.** A different OCR reading becomes "pending" and only
  replaces a block's text once it is seen again. This hides one-frame OCR
  misses and typewriter reveals, and costs one capture interval (100 ms at
  10 Hz) on a genuine subtitle change. A new block still needs one confirming
  frame before translation, so the latency budget in 2.1 is unchanged.
- **Jitter vs change.** Readings are "the same" at difflib ratio >= 0.9,
  except that differing numbers (counters, timers) and a reading that extends
  the other by two or more characters (typewriter) always count as changes.
- **Fragments.** Pieces of one row that the detector split (wide gaps, HUD
  columns) are merged before grouping; an unmatched group lying mostly inside
  a live block is treated as a fragment rather than a new block, and a block
  keeps its full box while a fragment of the same text is seen.
- **Client area only.** On a normal window the title bar and caption buttons
  were OCR'd and patched; by default only the client area is read
  (`--include-frame` restores the old behaviour). Borderless games have no
  frame, so this changes nothing for them.
- **Full-area cost.** The 1280x720 client area at ~106 ms per frame (median,
  HUD + subtitle) keeps up with the 10 Hz capture cap; the whole 1282x752
  frame including the title bar cost ~165 ms. With `--roi` the subtitle strip
  runs at the cap and the rest is swept every 10th frame.

Known gaps for later milestones: no text wrapping or shrinking beyond
single-line fitting (M3); colour sampling is a median of the border ring,
which fails on busy backgrounds (M3); the overlay is not tested on
multi-monitor setups.

## 11. M2 results (2026-10-21)

Built and tested offline; the live run against the API is still to do (no
API credentials on this machine yet).

What exists:

- **Claude backend** (`translate/claude.py`): one request per batch of stable
  blocks. The system prompt (rules, game name, glossary, style notes) is
  fixed per language pair and marked for prompt caching; the user message is
  a JSON document with target language, recent context pairs and numbered
  items; the reply is structured output parsed into a pydantic model, so no
  JSON repair is needed. Defaults: `claude-haiku-5-5`, effort `low`, adaptive
  thinking (the model skips thinking on simple requests at low effort; a
  `--no-thinking` switch sends `disabled` for measurement), `max_tokens`
  2048 to leave room for thinking, no sampling parameters (they return 400 on
  this model). A `refusal` or `max_tokens` stop reason raises; the service
  then cools the batch down instead of retrying at once.
- **Asynchronous service** (`translate/service.py`): the pipeline thread
  asks the cache for every stable untranslated block each frame and submits
  the misses as one batch to a worker pool; finished batches are folded into
  the cache on the next frame. In-flight texts are not resubmitted; failed
  texts wait a cooldown (default 3 s). The last ten (source, translation)
  pairs travel with each request as context.
- **Cache** (`translate/cache.py`), three tiers: exact match on normalised
  text; numeric reuse, where a cached translation is reused with its numbers
  swapped when only the digits changed (HUD counters, timers, prices,
  matched by value so reordering in Turkish is fine, and refused when a
  number is duplicated or spelled out); fuzzy match against the 200 most
  recent entries for OCR noise. Persisted as JSON per game and target
  language under `%APPDATA%\gametl\cache`.
- **CLI**: `--translator claude|uppercase|echo`, `--model`, `--effort`,
  `--no-thinking`, `--game`, `--glossary`, `--style`, `--target-lang` (default
  `tr`), `--source-lang` (defaults to the OCR language), `--cache-dir`,
  `--no-cache-file`. Credentials come from `ANTHROPIC_API_KEY`, also read
  from the Windows user environment if set after the terminal opened.

Measured with the uppercase translator through the full asynchronous path
on the fake game, 7 s: 4 requests for 5 unique texts, 11 cache hits (every
HUD timer tick served by numeric reuse), 0 errors, cache file written. The
same run before the numeric tier made 9 requests, nearly all for the timer.

Lessons:

- Changing numbers are the main request sink in a HUD; the numeric tier
  removes it without any per-game configuration. Ignore zones (M3) remain
  useful for text that should not be touched at all.
- A bug worth remembering: `cache or TranslationCache()` replaced the
  file-backed cache with an empty one because an empty cache has length 0.
- Prompt caching needs a minimum prefix length that a short system prompt
  does not reach; the cache marker is harmless and starts paying off once a
  glossary makes the prompt long.

### Live results (2026-10-21, Haiku 5.5, effort low, this machine)

First live run, 12 s on the fake game, structured output + adaptive thinking:
8 requests, 9 items, 10 cache hits, 0 errors, request latency median 1.97 s
(1.06-3.69 s), 1406 input + 366 output tokens plus 4422 cache-read and 1474
cache-write tokens, about $0.00055. Translations read well, e.g. "We leave
at dawn. Pack only what you can carry." -> "Şafakta yola çıkıyoruz. Sadece
taşıyabileceğin kadarını al." Two problems: latency far above the 0.5-0.8 s
budget, and the HUD timer sent four requests because each tick arrived while
the previous one was still in flight.

Benchmark (`scripts/bench_translate.py`, same 2-item batch, 4 calls each):

| Mode                          | First call | Then median | Output/call |
| ----------------------------- | ---------- | ----------- | ----------- |
| adaptive thinking, structured | 1.9 s      | 1.49 s      | 78 tok      |
| thinking off, structured      | 3.3 s      | 1.46 s      | 80 tok      |
| adaptive thinking, plain JSON | 1.1 s      | 1.14 s      | 77 tok      |
| thinking off, plain JSON      | 1.0 s      | 0.99 s      | 85 tok      |

Findings and decisions:

- **Structured output costs ~0.5 s per call** on this model. Plain JSON
  requested in the prompt and parsed locally is now the default; malformed
  output raises and the batch is retried after the cooldown. `--structured`
  keeps the guaranteed-shape mode.
- **Thinking makes no difference at low effort**: output stays ~80 tokens
  either way, so the model already skips it. Default is now `disabled`
  (`--thinking adaptive` to re-enable).
- **Prompt caching** engages in structured mode (the schema makes the prefix
  long enough: 737 cached tokens) but not in plain mode (483-token prompt,
  under the minimum). Cost is negligible either way.
- **In-flight counters**: `submit()` now skips a text whose numeric template
  is already in flight; the answer serves it by number swap.
- **Real latency floor** for a fresh line with Haiku from here is about
  1.0 s per request (network round trip plus ~80 output tokens), so a new
  subtitle shows its Turkish about 1.2-1.4 s after appearing, not the 0.5-
  0.8 s estimated in 2.1. Repeated and number-only changes stay instant. The
  fast paths in 2.1 (local draft then refine, pre-translated script) are the
  way under 0.5 s; a leaner reply format (array of strings instead of
  id/text objects) would shave perhaps 20 % more.
- Turkish fit on screen so far: the sampled lines were as long as or shorter
  than the English, and the single-line fitter handled them. Longer ones
  will need M3 wrapping.

Second live run with the new defaults (plain JSON, thinking off), 12 s:
5 requests for 6 items, 16 cache hits, 0 errors; the HUD timer cost one
request instead of four. Request latency median 1.57 s (0.99-1.92 s) for
single-item batches, higher than the benchmark's 1.0 s: network variance
from this machine dominates. 3067 input + 256 output tokens, about $0.0004.
Per hour of dialogue-heavy play that is a few cents, as estimated.

## 12. M3 results (2026-10-21)

What exists:

- **Fitter** (`layout/fit.py`, pure, measurement injected): for a
  translation longer than the source it tries, in order, shrinking the font
  down to 72 % of the source size while wrapping inside the source box;
  keeping the size and growing the box into free space (toward the side
  with more room, so subtitles grow upward and HUD lines downward); shrinking
  further to a 10 px floor; truncating with an ellipsis. Explicit newlines
  stay paragraph breaks. The pipeline reports the free space to the next
  block above and below (4 px margin) and to the edge of the client area.
- **Colour analysis** (`layout/colors.py`): besides background and text
  colours it reports `busy` (robust spread of the ring, or of inner pixels
  clearly on the background side, above 28 luminance levels, using the
  median absolute deviation so an anti-aliased glyph fringe inside the ring
  does not count) and `contrast`. `--style auto` draws a patch unless busy
  or contrast under 60, then a translucent (alpha 215) rounded pill with
  white outlined text. Outlines are eight offset draws in dark, then the
  text.
- **Jitter smoothing** (tracker): with unchanged text, box edge moves of
  3 px or less are ignored; larger moves are followed. One-frame fragments
  already kept the full box.
- **Ignore zones and patterns** (`tracking/filters.py`): OCR lines whose
  centre lies in a zone, or whose text matches a pattern, are dropped before
  tracking. `--ignore x,y,w,h` and `--ignore-pattern REGEX`, both repeatable.
- `scripts/fake_game.py --busy` draws a mosaic behind the subtitle band; the
  `verbose` dummy translator doubles every line.

Verified on the fake game: a doubled subtitle wraps to three lines at full
size and grows upward from the bottom edge; on the mosaic the subtitle gets
the pill and stays readable; the HUD disappears under an ignore zone; 63
tests pass.

Known gaps: colour sampling still assumes one text colour per block; text
with a gradient or two colours (speaker name + line) gets one; the fitter
does not reflow a source that was already two lines into one; growth never
pushes neighbouring blocks, it only avoids them.

## 13. M4 results (2026-10-21)

What exists:

- **Settings and profiles** (`app/config.py`): one `Settings` dataclass
  holds every option; profiles are Settings as JSON under
  `%APPDATA%\gametl\profiles\<slug>.json`, `config.json` remembers the last
  profile, and a profile matches a game by a title substring. Unknown keys
  in older or newer files are ignored.
- **Controller** (`app/controller.py`): builds the OCR engine (cached per
  language), translator, cache, service, overlay and pipeline thread from a
  Settings object; start/stop/pause/rescan; shared by the CLI, the tray and
  the settings window. Pause keeps capturing but shows and translates
  nothing; rescan drops all tracked blocks.
- **Global hotkeys** (`app/hotkeys.py`): Win32 RegisterHotKey on the thread
  queue, delivered through a Qt native event filter; combos like
  `ctrl+shift+t`, `alt+f5`; a combo another program owns is reported, not
  fatal.
- **Tray** (`app/tray.py`): icon drawn in code with a status dot; menu with
  status, Start/Stop, Pause, Rescan, Settings, Profiles, data folder, Quit;
  double-click opens settings.
- **Settings window** (`app/settings_dialog.py`): tabs for game (window
  picker with refresh, zone, ignores), translation, appearance, hotkeys;
  "Apply and run" and "Save profile".
- **CLI** (`app/main.py`): same options as before plus `--tray`,
  `--profile`, `--save-profile`, `--data-dir`; with no window it runs the
  tray and opens settings. Command-line options override the loaded
  profile only when given.

Verified on the fake game: profile saved from the CLI, tray mode started
from that profile with the overlay running, bare tray launch opens the
settings window and exits cleanly; 78 tests pass (config, hotkey parsing and
registration, dialog round trip, CLI override rules).

Not covered: the tray and dialog are exercised by launch and round-trip only,
not by simulated clicks; hotkeys are registered in tests but not pressed;
first-run experience on a machine without the OCR models downloads them
during "Apply and run" with only a status line to show for it.

## 14. M5 results (2026-10-21)

What exists:

- **Offline backend** (`translate/offline.py`): CTranslate2 + SentencePiece
  running the model from an Argos Translate package, downloaded straight
  from the Argos package index (the `argostranslate` runtime was avoided
  because it drags in PyTorch; the package zip is unpacked without its
  stanza sentence splitter). Lines are split into sentences on punctuation,
  all sentences of a batch go through one `translate_batch`, and line breaks
  are preserved. `gametl --download-model` fetches the pair's package into
  `%APPDATA%\gametl\models`; `--translator offline` runs without the API.
- **Draft-then-refine** (`translate/service.py`): the service takes an
  optional draft translator; `submit()` sends a draft batch and a final
  batch at the same time, `lookup_best()` returns the cached final answer
  if there is one, else the draft. The pipeline shows the draft and keeps
  the block flagged so the final replaces it on arrival. Drafts live only in
  memory; the cache holds finals.
- **Script pre-translation** (`translate/pretranslate.py`,
  `gametl-pretranslate`): loads .txt / .srt / .json / .csv, strips tags and
  duplicates, skips lines already cached, and writes into the same per-game
  cache the overlay reads. Sync mode chunks through the normal API; batch
  mode builds Batches API requests in plain-JSON reply mode, saves the job
  (batch id + chunk texts) so it can be collected later with `--resume`,
  and defaults to Opus 5.5 at half price.

Live results on this machine:

| Run                                   | Result                                                        |
| ------------------------------------- | ------------------------------------------------------------- |
| Offline model download (en->tr)       | Argos translate-en_tr 1.5, 129 MB, loads in ~0.4 s            |
| Offline per line                      | 12-26 ms single, ~60-70 ms per batch in the service           |
| Offline-only overlay run              | 4 lines translated, latency median 68 ms, no API              |
| Draft then refine (offline + Haiku)   | drafts median 53 ms, finals median 1.06 s, 0 errors          |
| Sync pre-translation, 5 lines, Haiku  | 1 call, 560 in / 194 out tokens                               |
| Overlay from the pre-translated cache | 0 requests, 4 cache hits                                      |
| Batch pre-translation, 5 lines, Opus  | 2 chunks, ended in ~3 min, 5 lines collected, 0 failed        |

Offline quality is draft-grade: "We leave at dawn. Pack only what you can
carry." became "Sabahtan ayrıldık. Sadece ne taşıyabilirsiniz." (wrong
tense, broken second sentence), while the same line from Haiku was
"Şafakta yola çıkıyoruz. Sadece taşıyabileceğin kadarını al." The draft
tier is for the first second only; a player who reads the drafts should
expect roughness.

Two problems found by the live runs:

- The first batch job failed on every chunk with "thinking.type.disabled is
  not supported for this model": the pre-translation command defaults to
  Opus 5.5, which rejects disabled thinking, while the translator had been
  sending it for every model. The translator now sends `disabled` only to
  models that accept it (Haiku 5.5, Opus 5) and leaves Opus 5.5 and
  Sonnet 5.5 on adaptive thinking. Batch failures now print the error.
- A subtitle change left the previous translation's patch, narrower than
  the new line, drawn over it for a frame, so the new line's ends poked out.
  The tracker now hides a block's translation the moment a different
  reading appears (the old reading and box are still kept, so one-frame OCR
  misses and typewriter reveals do not spawn new blocks); if the reading
  turns out to be jitter, the cache restores the translation a frame later.

Unit tests cover the loaders, chunking, the batch request shape,
submit/save/collect with a stub client, the draft tier ordering, the model
rule for disabled thinking, and the offline translator's batching and line
handling with stand-ins; 91 tests pass.

## 15. M6 results (2026-10-21)

What exists:

- **Build** (`gametl.spec`, `scripts/build.py`): `uv run --group build
  python scripts/build.py` makes `dist/gametl/`, a one-folder PyInstaller
  build with two executables over one runtime: `gametl.exe` (windowed tray
  app) and `gametl-cli.exe` (console; also `gametl-cli pretranslate ...`,
  since the main entry point dispatches that subcommand so one analysis
  serves both tools). The icon is generated from the tray drawing at build
  time. rapidocr's package data is bundled minus any models a development
  install downloaded; ctranslate2 and onnxruntime DLLs are collected
  explicitly; unused Qt modules are excluded.
- **First run**: the OCR engine now takes a model directory, and the
  controller points it at `%APPDATA%\gametl\models\ocr`, so a fresh machine
  downloads the two PP-OCRv6 small models (~20 MB) on first "Apply and run"
  with a status line; the offline model downloads from the new "Download
  offline model" button in the settings window (or `--download-model`).
- **No console**: the windowed executable redirects its output to
  `%APPDATA%\gametl\gametl.log`, truncated when it passes 5 MB.

Measured: build takes about 50 s; `dist/gametl` is 402 MiB, of which
OpenCV 112, PySide6 92, CTranslate2 60, ONNX Runtime 38, numpy 21, Pillow
13. Verified with the fake game: the console build lists windows, runs the
overlay from a fresh data folder (downloading the OCR models first) and
saves a screenshot; the windowed build runs tray mode and writes the log;
the pretranslate subcommand responds.

Size levers for later: `opencv-python-headless` 5.0 is the largest item and
is used only for resizing, colour conversion and the debug drawings, so a
slimmer image library could save ~100 MB; the OpenCV and Qt DLLs are not
compressed (UPX is off). A one-file build was not attempted: the start-up
unpack would add seconds for no benefit on a tray app.

Not covered: no installer and no code signing (SmartScreen will warn on an
unsigned download), no start-with-Windows entry, not tested on a machine
without the Visual C++ runtime that Python wheels assume.

## 16. First real-game feedback (2026-10-21)

Finding: on a real game the app translated everything on screen, which is
far more than wanted; the useful target is one area, typically the subtitle
strip.

Change: zone-only is now the default behaviour and the zone is chosen on
screen.

- **Area selector** (`overlay/selector.py`): a dimmed layer over the game
  window; drag a rectangle (Esc cancels, drags under 8 px count as cancel).
  The rectangle is converted to fractions of the client area so it survives
  window moves and resizes.
- **Hotkey and menu**: `select` hotkey (default Ctrl+Shift+A), "Select area
  to translate..." and "Clear area" in the tray, "Select on screen" next to
  the area field in settings. The controller restarts the pipeline on the
  new area at once; the tray writes it into the loaded profile.
- **Default**: with an area set, nothing outside it is read any more
  (`full_scan_every` default changed from 10 to 0; the sweep remains as an
  option).

Verified on the fake game: a command-line run with a zone over the subtitle
strip left the HUD untouched with no ignore zone configured; a scripted
drag on the selector restarted the pipeline on the selected area.

Open from the same run: everything else the real game showed (fonts, frame
rate, scaling) still has to be reported; the selector covers only one area,
and a second one (e.g. a dialogue box plus a choice menu) would need a list.

## 17. Second real-game feedback: draft quality and Haiku latency (2026-10-21)

Finding: with a selected subtitle area the overlay works well, but the
Argos draft is too poor to read and Haiku's round trip is too slow for
short lines that are only up briefly.

Changes:

- **OPUS-MT offline models.** `scripts/convert_offline_model.py` converts
  Helsinki-NLP/opus-mt-tc-big-<src>-<tgt> (or any Marian model) to
  CTranslate2 in a throwaway environment with PyTorch; the app loads it with
  the model's own source and target SentencePiece files and prefers it over
  the Argos package. One trap cost an hour: Marian models need the `</s>`
  end-of-sentence token appended to the source tokens (the HF tokenizer adds
  it silently); without it the decoder never stops and repeats to the length
  limit. With it, English to Turkish output is close to Claude's on short
  lines ("I told you not to open that door." -> "Sana o kapıyı açma
  demiştim.", "Health potion" -> "Sağlık iksiri") at ~20 ms per line, where
  Argos gave "Size o kapıyı açmamamı söyledim." and "Sağlık potayonu". A
  `no_repeat_ngram_size=3` guard stays on as a safety net. The converted
  en->tr model is installed in this machine's data folder.
- **DeepL backend** (`translate/deepl.py`): optional main translator or
  draft, keyed by `DEEPL_AUTH_KEY` (free tier), a few hundred milliseconds,
  strong for Turkish. Tested against a stub only; no key on this machine.
- **Claude trims.** The system prompt was cut to a third of its length and
  the plain reply format is now a positional string list (no ids). Input
  tokens 482 -> 316, output 85 -> 62 per two-line batch. Measured effect:
  median 0.99 s -> 0.93 s per request. The round trip from this network
  dominates; Haiku will not get meaningfully faster from here, so short,
  briefly shown lines need the draft tier, and that tier is now good.

What the user should see now with `--draft offline`: the OPUS draft within
about 0.1 s of a line appearing, replaced by Claude's wording a second later
(often nearly identical).

## 18. Third real-game feedback: draft still weak, inconsistent sizing (2026-10-22)

Findings: the OPUS draft is better but still "pretty bad" on the game's
lines; and translated subtitles came out in different sizes from line to
line although the game's subtitles are uniform.

Sizing, diagnosed: each block's font size was derived from its own OCR box
height, which varies with the letters in the line (descenders, capitals,
punctuation), and the fitter's first move for a long Turkish line was to
shrink it to fit the width while short lines stayed full size.

Changes:

- **Style memory** (`layout/style.py`): per horizontal band of the frame
  (64 px, neighbours included), the median source line height, median
  background and text colours, and a majority vote on busy-background, from
  the last 24 blocks seen there. Every block in the subtitle zone renders
  with the band's size, colours and style once two have been seen; the
  current box's own height is not included in the median, since it is the
  jitter being removed. Reset with rescan and area changes.
- **Wrap before shrink** (`layout/fit.py`, `prefer_grow`): when there is
  room, a long translation wraps to a second line at the same size (growing
  toward the side with more room, so upward for subtitles) instead of being
  shrunk; shrinking remains the fallback when nothing can grow.

Draft quality: offline MT for English to Turkish on game dialogue tops out
around the OPUS tc-big model. With a DeepL free key in place, a live
comparison on ten game lines (single-line requests from this machine):

| Backend    | Median latency | Range        | Quality on the ten lines                   |
| ---------- | -------------- | ------------ | ------------------------------------------ |
| DeepL      | 196 ms         | 166-733 ms   | natural throughout; no misses              |
| Haiku 5.5  | 930 ms         | 674-1117 ms  | natural; one awkward choice ("Yakında kal") |

Decision: for English to Turkish, DeepL as the main translator with no
draft is the best arrangement (no handover, five times faster, equal or
better wording); Claude stays available for its glossary, tone notes and
context, and for languages DeepL does not cover. The settings default stays
Claude because DeepL needs a key; the README recommends DeepL for Turkish.

## 19. Fourth real-game feedback: subtitle mode (2026-10-22)

Findings: DeepL alone "working very well"; styling still inconsistent even
with the style memory; and selecting a centred subtitle area by hand is
hard.

Changes:

- **Centred selection** (`overlay/selector.py`): with `center_zone` (on by
  default) the dimmed layer shows a centre guide and keeps the rectangle
  symmetric about the client area's horizontal centre while dragging, so a
  rough drag on one side yields a centred zone. `--no-center-zone` or the
  checkbox turn it off.
- **Subtitle render mode** (`render: subtitle`, the default when an area
  is set): the source line is still patched out under its sampled
  background colour, but the translation is no longer placed on the OCR
  box. It is drawn in one fixed style: a fixed font size
  (`subtitle_font_px`; 0 = the game's own line height from the style
  memory), a fixed colour (`subtitle_color`, default white) with an
  outline, on a translucent pill (`subtitle_background`), centred
  horizontally in the zone and placed vertically on the source line, at the
  zone's bottom, or in its middle (`subtitle_position`). Long lines wrap at
  the fixed size within the zone. `render: inplace` restores per-block
  placement with the style memory.
- Settings window: Render, font size, colour, background, position and
  centring on the Appearance tab; command-line equivalents.

- **Hiding the source line**: a flat patch in the sampled background
  colour when the background is flat; a dark rounded band when the style
  memory says the background is busy, because a flat rectangle over
  artwork looks like a glitch while a dark band reads as a subtitle
  background. (Seen by accident: a test screenshot taken while the user's
  real game was in front showed the patch as a navy rectangle over the
  scene.)

Verified on the fake game: with a zone over the subtitle strip, a doubled
line renders centred in the zone on a pill (it wraps once the zone is
narrower than the line); a fixed 30 px size at the zone bottom renders
every line identically; 107 tests pass.

## 20. Crash in subtitle mode, and one pill instead of a patch (2026-10-22)

Finding: "sometimes it crashes". The Windows event log held two APPCRASH
events (01:09 and 01:12) for the 01:03 build: access violation in
Qt6Gui.dll, same offset both times. Reproduced in a script: for a
one-word subtitle ("Run!") the word wrapper never measures anything, so
the font size was never registered, the subtitle painter raised
`KeyError` on the missing metrics in the middle of `paintEvent`, the
painter was never ended, and Qt faulted on a later paint. Short lines
made it intermittent.

Fixes: the painter registers the font before reading its metrics; every
`paintEvent` ends its painter in a `finally` and logs a paint exception
(three at most) instead of corrupting Qt; `faulthandler` now writes the
Python stacks of all threads to the log on any native crash, so the next
one, if any, names its line. The subtitle layout cache is capped and the
per-frame OCR timing list is bounded, after a Windows "pre-leak" warning
the day before pointed at slowly growing memory.

Cover: the user asked why the original line is covered at all when the
pill is already there. The pill was translucent (alpha 200), so the
original would ghost through it, and when the subtitle is placed at the
zone's bottom or middle the original is not under it at all. Now there is
no flat patch in subtitle mode: the pill is near-opaque (alpha 230) and,
when it overlaps the source line, it is widened to one shape covering
both; when the subtitle sits elsewhere, a matching dark band hides the
source line unless "hide the original line" is turned off
(`subtitle_hide_source`, `--show-source`).
