# gametl

Real-time in-game text translation overlay for Windows. Captures a game window,
reads on-screen text with local OCR, translates it with Claude, and draws the
translation over the original at the same position.

Design: see [PLAN.md](PLAN.md). Status: M5 (offline draft translation,
draft-then-refine, script pre-translation).

## Setup

Requires Python 3.12 (3.15 is too new for the compiled dependencies). With
[uv](https://docs.astral.sh/uv/):

```
uv python install 3.12
uv sync
```

This creates `.venv` with Python 3.12 and every dependency, and installs the
`gametl` package in editable mode.

Long-path caveat: if the project folder path is long (this is the case while
it lives in the folder the app created for the session), a venv inside it hits
the Windows 260-character path limit and some imports fail. Either keep the
project at a short path such as `C:\code\gametl`, or put the venv elsewhere by
dot-sourcing `scripts\env.ps1` before every `uv` command:

```
. .\scripts\env.ps1
uv sync
```

## Run the app

Translation uses Claude through the Anthropic API. Put your key in the
`ANTHROPIC_API_KEY` environment variable (Windows: Settings > System > About >
Advanced system settings > Environment Variables; the app also reads it from
the user environment if it was set after the terminal opened).

```
uv run gametl
```

With no options this puts an icon in the tray and opens the settings window:
pick the game window from the list (Refresh after launching the game), set
languages and translator, then "Apply and run". "Save profile" stores the
settings under `%APPDATA%\gametl\profiles` so the game can be started from
the tray's Profiles menu next time. The tray menu also has Start/Stop, Pause,
Rescan and the data folder.

Default global hotkeys (changeable in the Hotkeys tab):

| Hotkey | Action |
| --- | --- |
| Ctrl+Shift+T | start / stop the overlay |
| Ctrl+Shift+P | pause / resume (hides translations, keeps running) |
| Ctrl+Shift+R | rescan: forget tracked blocks and read the screen afresh |
| Ctrl+Shift+S | open settings |

From the command line, with the game in borderless or windowed mode:

```
uv run gametl --window "Part of the window title"
```

`--profile NAME` loads a saved profile first and explicit options override
it; `--save-profile NAME` stores the resulting options; `--tray --window ...`
starts at once with the tray icon.

The overlay follows the window, reads its English text, and patches each block
with the Turkish translation in the sampled background and text colours.
Translations are cached per game under `%APPDATA%\gametl\cache`, so repeated
lines show instantly and cost nothing.

Translation options:

- `--target-lang de` / `--source-lang ja` change the pair (`--lang` picks the
  OCR model; the source language defaults to it).
- `--model claude-opus-5-5` for the quality setting; `--effort low|medium|high`;
  `--thinking adaptive` lets the model think (off by default: measured no
  gain); `--structured` uses server-side structured output (guaranteed JSON,
  about 0.5 s slower per call).
- `--game "Name"` names the game in the prompt and the cache file;
  `--glossary terms.json` fixes renderings of names and terms;
  `--tone "..."` adds notes on tone and formality.
- `--translator uppercase` runs the whole pipeline without any API calls;
  `--translator verbose` doubles every line to exercise wrapping.

Faster than the API round trip:

- **Offline draft.** `uv run gametl --download-model --target-lang tr` fetches
  an Argos Translate package (a CTranslate2 model, no PyTorch) for the pair
  into `%APPDATA%\gametl\models`. Then `--draft offline` (or Draft: offline in
  the settings window) shows the offline translation within a fraction of a
  second and swaps in Claude's when it arrives. `--translator offline` runs
  fully offline with no API at all, at lower quality.
- **Pre-translate the script.** If the game's text can be extracted (a text
  file with one line per entry, an .srt, a JSON file or a CSV), translate it
  once up front so every line is instant in play:

  ```
  uv run gametl-pretranslate script.txt --game "Fake Game"
  ```

  By default this uses Opus 5.5 through the Batches API at half price and
  waits up to ten minutes; `--wait 0` submits and exits, and
  `--resume JOBFILE` collects later. `--sync` uses the normal API at once.
  The `--game` name must match the one the overlay runs with, since it names
  the cache file.

Appearance and ignores:

- Translations longer than the original shrink a little, then wrap and grow
  the box into free space (toward the side with more room), then shrink
  further, then truncate with an ellipsis.
- `--style auto` (default) patches the original out with its background
  colour, but switches to a translucent pill with outlined text where the
  background is busy or the contrast is low; `--style patch|pill|outline`
  forces one.
- `--ignore 0,0,0.5,0.1` (repeatable) never translates text in that zone of
  the client area; `--ignore-pattern "^\d+$"` (repeatable) drops OCR lines
  matching a pattern.

Useful options:

- `--roi 0,0.75,1,0.25` OCR only the subtitle strip at full rate and the rest
  of the frame once every `--full-scan-every` frames.
- `--lang japan` (or `ch`, `korean`, `de`, ...) selects the OCR model.
- `--debug` outlines every tracked block and prints per-frame stats;
  `--dump-dir out/dump` also saves each frame with OCR lines and blocks drawn.
- `--no-hide-unfocused` keeps the overlay up when the game is not in front.
- `--run-for 8 --screenshot out/overlay.png` runs for 8 s and saves what the
  screen looked like, overlay included (add `--capturable`).

Try it without a game:

```
uv run python scripts/fake_game.py
```

```
uv run gametl --window "Fake Game" --debug
```

## M0 spike: capture + OCR

List capturable windows:

```
uv run python scripts/spike_capture_ocr.py --list-windows
```

Capture a window for a few seconds, OCR every frame, print text, boxes and
timings, and save the last annotated frame to `out/`:

```
uv run python scripts/spike_capture_ocr.py --window "Notepad" --seconds 5
```

Run OCR on a screenshot instead of a live window:

```
uv run python scripts/spike_capture_ocr.py --image path\to\screenshot.png
```

No game at hand? `scripts/fake_game.py` opens a stand-in window with a HUD and
a large subtitle that changes every few seconds (`--typewriter` reveals it
character by character). In a second terminal:

```
uv run python scripts/fake_game.py
```

```
uv run python scripts/spike_capture_ocr.py --window "Fake Game" --roi 0,0.75,1,0.25
```

Tests:

```
uv run pytest
```

## Layout

```
src/gametl/
  capture/    window-targeted screen capture (Windows Graphics Capture)
  ocr/        text detection + recognition (RapidOCR, Windows OCR)
  tracking/   line -> block grouping, cross-frame matching, stability gate
  translate/  Translator interface, Claude backend, cache, batching
  layout/     fitting translated text into the source box, colour sampling
  overlay/    transparent click-through window that follows the game
  app/        tray icon, settings, hotkeys, per-game profiles
scripts/      spikes and tools
tests/
```
