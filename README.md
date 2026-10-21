# gametl

Real-time in-game text translation overlay for Windows. Captures a game
window, reads the text on screen with local OCR, translates it (DeepL,
Claude, or an offline model), and draws the translation over the game as a
subtitle in the area you select.

Design notes and the history of decisions: [PLAN.md](PLAN.md).

## Packaged build (no Python needed)

```
uv run --group build python scripts/build.py
```

produces `dist/gametl/` with two executables that share one runtime:
`gametl.exe` (the tray app; its output goes to `%APPDATA%\gametl\gametl.log`)
and `gametl-cli.exe` (the same app with a console, for command-line use and
`gametl-cli pretranslate ...`). Copy the folder anywhere and run
`gametl.exe`. The OCR models (about 20 MB) download on first run into
`%APPDATA%\gametl\models`, as does the offline model when you press
"Download offline model" in the settings window. API keys are read from the
`DEEPL_AUTH_KEY` and `ANTHROPIC_API_KEY` user environment variables.

## Using it

Run `gametl.exe` (or `uv run gametl` from a checkout). With no options this
puts an icon in the tray and opens the settings window: pick the game window
from the list (Refresh after launching the game), set the languages and the
translator, then "Apply and run". "Save profile" stores the settings under
`%APPDATA%\gametl\profiles` so the game can be started from the tray's
Profiles menu next time. The tray menu also has Start/Stop, Pause, Rescan,
area selection and the data folder.

Most games show far more text than you want translated (HUD, menus, item
names). Press **Ctrl+Shift+A** with the game in front and drag a rectangle
over the subtitle area: from then on only that area is read and translated,
and the choice is saved in the profile as fractions of the window, so it
survives resizing. The rectangle is kept centred horizontally while you drag
(a guide line marks the centre), so one edge and the height are enough.
"Select area to translate" and "Clear area" are also in the tray menu and
next to the area field in settings.

With an area selected, translations are rendered as subtitles: one fixed
font size (the game's own by default, or a number in Appearance), one colour
with an outline, on a near-opaque pill centred in the area and placed on the
line the game drew. The pill covers the original line; when the subtitle is
placed at the bottom or middle of the area instead, a matching dark band
hides the original (switch that off with "hide the original line"). Long
translations wrap at the same size. Switch Render to `inplace` in Appearance
to put each translation on its own OCR box instead, patched out in the
game's own colours.

Default global hotkeys (changeable in the Hotkeys tab):

| Hotkey | Action |
| --- | --- |
| Ctrl+Shift+A | select the area to translate (drag a rectangle; Esc cancels) |
| Ctrl+Shift+T | start / stop the overlay |
| Ctrl+Shift+P | pause / resume (hides translations, keeps running) |
| Ctrl+Shift+R | rescan: forget tracked blocks and read the screen afresh |
| Ctrl+Shift+S | open settings |

### Which translator

- **DeepL** (recommended for Turkish and other European languages): put a
  key in the `DEEPL_AUTH_KEY` environment variable (free tier: 500k
  characters a month) and choose Translator `deepl`. Measured for English to
  Turkish: median 0.2 s per line with natural wording.
- **Claude** (the default, needs `ANTHROPIC_API_KEY`): about 0.9 s per line
  with Haiku 5.5. Choose it when you need a glossary, tone notes, context
  between lines, or a language DeepL lacks. `claude-opus-5-5` is the quality
  option.
- **Offline**: no network at all. Draft `offline` shows an offline
  translation within a fraction of a second and swaps in the main
  translator's when it arrives; Translator `offline` runs with no API. Two
  model sources, both under `%APPDATA%\gametl\models`: the OPUS-MT model
  for the pair, converted once with
  `uv run --with torch --with transformers --with huggingface_hub python scripts/convert_offline_model.py --source en --target tr`
  (about 230 MB; the conversion needs PyTorch, the app does not), or the
  smaller and weaker Argos package from `gametl --download-model` or the
  settings button. The converted model is preferred when both exist.

Translations are cached per game under `%APPDATA%\gametl\cache`, so repeated
lines show instantly and cost nothing. If the game's script can be extracted
(a text file with one line per entry, an .srt, a JSON file or a CSV),
translate it once up front so every line is instant in play:

```
uv run gametl-pretranslate script.txt --game "Fake Game"
```

By default this uses Opus 5.5 through the Batches API at half price and
waits up to ten minutes; `--wait 0` submits and exits, and `--resume JOBFILE`
collects later; `--sync` uses the normal API at once. The `--game` name must
match the one the overlay runs with, since it names the cache file.

OCR sometimes reads a number or a symbol out of background detail. Ignore
patterns (Game tab, one regular expression per line, case-insensitive) drop
such lines: `^[^a-z]+$` drops every line without a letter.

## Command line

With the game in borderless or windowed mode:

```
uv run gametl --window "Part of the window title"
```

`--profile NAME` loads a saved profile first and explicit options override
it; `--save-profile NAME` stores the resulting options; `--tray --window ...`
starts at once with the tray icon. `gametl --help` lists every option; the
useful ones:

- `--target-lang de` / `--source-lang ja` change the pair (`--lang` picks the
  OCR model: `en`, `japan`, `ch`, `korean`, `de`, ...; the source language
  defaults to it).
- `--translator deepl|claude|offline`, `--draft offline|deepl`,
  `--model claude-opus-5-5`, `--effort low|medium|high`, `--thinking adaptive`
  (off by default: measured no gain), `--structured` (server-side structured
  output, guaranteed JSON, about 0.5 s slower per call).
- `--game "Name"` names the game in the prompt and the cache file;
  `--glossary terms.json` fixes renderings of names and terms;
  `--tone "..."` adds notes on tone and formality.
- `--roi 0,0.75,1,0.25` reads and translates only that area (fractions of the
  client area); `--render inplace`, `--subtitle-font 30`,
  `--subtitle-color "#FFEE00"`, `--subtitle-position bottom`.
- `--ignore 0,0,0.5,0.1` (repeatable) never translates text in that zone;
  `--ignore-pattern "^[^a-z]+$"` (repeatable) drops OCR lines matching a
  pattern.
- `--translator uppercase` runs the whole pipeline without any API calls;
  `--translator verbose` doubles every line to exercise wrapping.
- `--debug` outlines every tracked block and prints per-frame stats;
  `--dump-dir out/dump` also saves each frame with OCR lines and blocks drawn;
  `--run-for 8 --screenshot out/overlay.png --capturable` runs for 8 s and
  saves what the screen looked like, overlay included.

Try it without a game: `scripts/fake_game.py` opens a stand-in window with a
HUD and a large subtitle that changes every few seconds (`--typewriter`
reveals it character by character, `--busy` draws artwork behind it).

```
uv run python scripts/fake_game.py
```

```
uv run gametl --window "Fake Game" --translator verbose --roi 0,0.75,1,0.25
```

## Development

Requires Python 3.12 (3.15 is too new for the compiled dependencies). With
[uv](https://docs.astral.sh/uv/):

```
uv python install 3.12
uv sync
```

This creates `.venv` with Python 3.12 and every dependency, and installs the
`gametl` package in editable mode. Tests, lint and formatting:

```
uv run pytest
uv run ruff check src tests scripts
uv run ruff format src tests scripts
```

`scripts/spike_capture_ocr.py` is a diagnostic that captures a window and
prints what OCR sees, with timings, without the overlay:

```
uv run python scripts/spike_capture_ocr.py --window "Fake Game" --roi 0,0.75,1,0.25
```

`scripts/bench_translate.py` measures Claude request latency per
configuration (makes real API calls).

Layout:

```
src/gametl/
  capture/    window-targeted screen capture (Windows Graphics Capture)
  ocr/        text detection and recognition (RapidOCR on ONNX Runtime)
  tracking/   lines -> blocks, cross-frame matching, stability gate, ignore filters
  translate/  Translator interface, Claude / DeepL / offline backends, cache, service
  layout/     fitting text into the source box, colour sampling, consistent styling
  overlay/    transparent click-through window, area selector
  app/        controller, pipeline thread, tray icon, settings window, hotkeys, profiles
scripts/      fake game, diagnostics, build, model conversion
tests/
```
