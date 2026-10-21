# gametl

Real-time in-game text translation overlay for Windows. Captures a game window,
reads on-screen text with local OCR, translates it with Claude, and draws the
translation over the original at the same position.

Design: see [PLAN.md](PLAN.md). Status: M2 (real translation with Claude,
English to Turkish by default).

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

## Run the overlay

Translation uses Claude through the Anthropic API. Put your key in the
`ANTHROPIC_API_KEY` environment variable (Windows: Settings > System > About >
Advanced system settings > Environment Variables; the app also reads it from
the user environment if it was set after the terminal opened). Then start the
game in borderless or windowed mode and run:

```
uv run gametl --window "Part of the window title"
```

The overlay follows the window, reads its English text, and patches each block
with the Turkish translation in the sampled background and text colours.
Translations are cached per game under `%APPDATA%\gametl\cache`, so repeated
lines show instantly and cost nothing.

Translation options:

- `--target-lang de` / `--source-lang ja` change the pair (`--lang` picks the
  OCR model; the source language defaults to it).
- `--model claude-opus-5-5` for the quality setting; `--effort low|medium|high`.
- `--game "Name"` names the game in the prompt and the cache file;
  `--glossary terms.json` fixes renderings of names and terms;
  `--style "..."` adds tone notes.
- `--translator uppercase` runs the whole pipeline without any API calls.

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
