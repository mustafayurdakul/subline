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
| M3 | Layout quality     | Fit/wrap, background and colour sampling, hysteresis, ignore zones.                           | 2-3 days |
| M4 | App shell          | Tray icon, settings UI, window picker, hotkeys, per-game profiles, config in %APPDATA%.       | 2-3 days |
| M5 | Fast paths         | Offline NMT backend (CTranslate2), fast-first-then-refine mode, script import + batch pre-translation, fuzzy lookup at runtime. See 2.1. | 3-4 days |
| M6 | Packaging & extras | PyInstaller build, DirectML option, glossary editor, logs, predictive hiding (experimental).  | ongoing  |

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

Still to verify live: real latency per batch at low effort with and without
thinking, Turkish length versus the box (expected to need M3 wrapping), and
cost per hour of play.
