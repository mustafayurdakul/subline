# Subline

Real-time translation of in-game subtitles for Windows.

Subline captures a game window, reads the subtitle area with local OCR,
translates each line through DeepL, Claude or an offline model, and draws
the translation over the game in place of the original, about half a
second after a line appears. The package and the executable are named
`gametl`; the app presents itself as Subline.

Copyright (c) 2026 Mustafa Yurdakul. Proprietary software: free to try for
14 days, then a licence key is required (see [Licensing](#licensing)).

![Alan Wake 2: the game's English subtitle above, the same moment with Subline's Turkish subtitle below](docs/demo.gif)

*Alan Wake 2, English to Turkish: the game above, Subline below. Rendered
from a recording with the same pipeline the live overlay uses (see
[Rendering a demo](#rendering-a-demo)).*

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Getting started](#getting-started)
- [Translators](#translators)
- [Settings](#settings)
- [Command line](#command-line)
- [Rendering a demo](#rendering-a-demo)
- [Architecture](#architecture)
- [Development](#development)
- [Releases](#releases)
- [Acknowledgements](#acknowledgements)
- [Licensing](#licensing)

## Features

- **Works with any windowed or borderless game.** Capture goes through
  Windows Graphics Capture, so only the game window is read, whatever
  else is on screen.
- **Reads the area you choose.** Press a hotkey, drag a rectangle over
  the subtitle strip, and from then on only that strip is read. The choice
  is saved per game as fractions of the window, so it survives resizes.
- **Subtitles that look like subtitles.** One fixed size and colour,
  learned from the game's own text, in a font and weight of your choice,
  drawn on a dark pill, with a soft shadow, or bare with an outline,
  centred in the area.
  Long translations wrap at the same size.
- **Three translators.** DeepL (the default: fast, strong for European
  languages, free tier), Claude (glossary, tone notes, any language), or
  an offline CTranslate2 model (no network; an optional download). DeepL
  and Claude both see the recent lines as context, so names and pronouns
  stay consistent across a scene. A faster translator can show a draft
  while a slower one answers.
- **Nothing is translated twice.** A per-game cache answers repeated lines
  instantly, and a game's script can be translated up front in one batch.
- **Settings apply as you change them.** Edits in the settings window
  reach the running overlay as soon as the typing pauses.
- **Stays out of the way.** Tray icon, global hotkeys, per-game profiles,
  pause and rescan; the overlay hides when the game is not in front.

## Requirements

- Windows 10 (build 18362 or later) or Windows 11, 64-bit.
- The game in windowed or borderless-window mode. Exclusive fullscreen can
  be neither captured nor drawn over.
- For DeepL or Claude, an API key from [deepl.com](https://www.deepl.com/pro-api)
  (the free tier covers 500,000 characters a month) or
  [console.anthropic.com](https://console.anthropic.com/). The offline
  translator needs neither.

## Installation

### Packaged build

Unzip the release folder anywhere and run `gametl.exe`. The OCR models
(about 20 MB) download on first run into `%APPDATA%\gametl\models`. The
app runs as a 14-day trial until a licence key is entered on the Licence
page.

**Uninstall:** delete the unzipped folder. Everything else Subline keeps
lives in `%APPDATA%\gametl` (profiles, translation caches, downloaded
models and runtime, `config.json`, the log) and in four Windows Credential
Manager entries (`gametl/DEEPL_AUTH_KEY`, `gametl/ANTHROPIC_API_KEY`,
`gametl/LICENSE_KEY`, `gametl/TRIAL_START`). **Remove all data and quit**
on the Licence page, or `gametl --remove-all-data`, deletes both. Nothing
is written to the registry or to `%TEMP%`.

### From source

Needs [uv](https://docs.astral.sh/uv/) and a licence for use beyond the trial.

```
git clone git@github.com:mustafayurdakul/yurdakuls-gameclt.git
cd yurdakuls-gameclt
uv python install 3.12
uv sync
uv run gametl
```

`uv sync --extra offline` adds the offline translator's runtime to a
development install; the packaged app downloads it on demand instead.

## Getting started

1. Run Subline. A tray icon appears and the settings window opens on its
   **Game** page.
2. Pick the game window from the list (press **Refresh** after launching
   the game). The bottom quarter of the window is read by default; press
   **Select on screen** and drag a rectangle if the subtitles sit
   elsewhere.
3. On the **Translation** page, paste the DeepL key and press **Save**.
   Claude and the offline model are there too. Keys are kept in Windows
   Credential Manager, never in a profile file.
4. Press **Start** at the top right. While the overlay runs the button
   reads **Stop**. Save the settings as a profile from the box at the
   bottom left, so the game is recognised next time.

With the game in front, **Ctrl+Shift+A** selects the area at any time:
drag a rectangle, nudge it with the arrow keys (Shift: 10 px, Ctrl:
resize), Enter confirms, Esc cancels; holding Shift while dragging keeps
the rectangle centred, so one edge and the height are enough. Translations
appear in that area from then on, and the area is saved with the profile.

The pages: **Game** (window, area, what to ignore), **Translation**
(languages, translator, draft, keys, Claude options), **Appearance**
(size, colour, font, weight, pill or shadow, placement, with a live
preview drawn by the overlay's own painter),
**Hotkeys** (click a field and press the keys), **Licence** and
**Advanced** (capture rate, timing, the data folder). Every change takes
effect as soon as the typing pauses, on the running overlay too: the area,
the filters, the timing and the look reach it directly, and a new window,
language or translator restarts it.

Next time, start the game from the tray's **Profiles** menu or let the
window title match: the profile whose window it names loads on its own.

Default hotkeys (changeable on the Hotkeys page):

| Hotkey | Action |
| --- | --- |
| Ctrl+Shift+A | select the area to translate |
| Ctrl+Shift+T | start / stop the overlay |
| Ctrl+Shift+P | pause / resume (hides translations, keeps running) |
| Ctrl+Shift+R | rescan: forget tracked lines and read the screen afresh |
| Ctrl+Shift+S | open settings |

### Licence key

The Licence page shows how many trial days are left. Paste the key there
and press **Activate**; it is kept in Windows Credential Manager. From the
command line, `gametl --activate KEY` stores a key and
`gametl --license-status` prints the state.

## Translators

| Translator | Latency per line | Best for |
| --- | --- | --- |
| DeepL (default) | about 0.2 s | Turkish and other European languages |
| Claude Haiku 5.5 | about 0.9 s | glossaries, tone notes, consistency between lines, languages DeepL lacks; `claude-opus-5-5` for the best quality |
| Offline (OPUS-MT) | about 0.02 s | no network; good on short lines, weaker on long ones |

Latencies measured for English to Turkish on a desktop PC. The **Draft**
setting shows the offline or DeepL translation at once and replaces it
when the main translator answers.

### Offline translation

The offline translator is not part of the app itself. **Download** on the
Translation page (or `gametl --download-model`) fetches its runtime
(CTranslate2 and SentencePiece, about 20 MB, once) into
`%APPDATA%\gametl\runtime` and the Argos model for the language pair into
`%APPDATA%\gametl\models`. A stronger OPUS-MT model for a pair can be
converted once with

```
uv run --with torch --with transformers --with huggingface_hub python scripts/convert_offline_model.py --source en --target tr
```

(about 230 MB; the conversion needs PyTorch, the app does not) and is
preferred when present.

### Translating a script up front

If the game's script can be extracted (a text file with one line per
entry, an `.srt`, a JSON file or a CSV), translate it once so every line
is instant in play:

```
uv run gametl-pretranslate script.txt --game "Fake Game"
```

This uses Claude Opus 5.5 through the Batches API at half price and waits
up to ten minutes (`--wait 0` submits and exits, `--resume JOBFILE`
collects later, `--sync` uses the normal API at once). The `--game` name
must match the one the overlay runs with.

## Settings

Every setting has a command-line equivalent; `gametl --help` lists them.

- **Ignore patterns** (Game page): regular expressions, one per line,
  case-insensitive. Every new profile starts with one that drops any OCR
  line without a letter, which removes the stray digits OCR sometimes
  reads out of background detail. **Ignore zones** exclude rectangles.
  **Short lines need OCR confidence** (default 90 %) drops one- and
  two-letter lines OCR is unsure about; texts under four letters also
  need a second stable frame.
- **Render** (Appearance page): `subtitle` draws every line in one style
  centred in the selected area; `inplace` puts each translation on its own
  OCR box in the game's own colours. In subtitle mode the font size and
  the text colour are learned from the game's first lines and then held
  for the session (set a size or a `#RRGGBB` colour to override), the text
  sits on a steady baseline at the bottom of the area (**Position**
  `bottom`; `source` follows the game's own line), and the background is a
  `pill` (opacity below it), a `shadow` like the game's own text, or
  `none`. **Hide the original line** covers the game's own text when the
  translation is drawn elsewhere; off by default.
- **Font and Weight** (Appearance page): any font installed on the
  computer (default Segoe UI) and a weight from Regular to Bold (default
  SemiBold). The preview on the page is painted by the overlay's own
  code.
- **Only centred text** and **Only subtitle-sized text** (Appearance page)
  keep HUD prompts and objectives that share the area out of the
  subtitles: text whose centre is more than 10 % of the area's width off
  centre, or whose line height differs more than 35 % from the learned
  size, is left alone. Set either to 0 for games that left-align their
  subtitles.
- **Read on the GPU** (Translation page): DirectML on any DirectX 12 card.
  On an RTX 3080 Ti a full 1280x720 frame drops from 204 ms to 105 ms, but
  a subtitle strip goes from 54 ms to 71 ms: leave it off for a strip, turn
  it on for large areas.
- **Change that wakes OCR** (Advanced page, `--change-threshold`): OCR runs
  only when something in the read area has changed since the frame last
  read (the strongest local change in a small grey thumbnail, 0 to 255;
  default 20), so a short word appearing in a wide strip counts in full
  and a static screen costs no OCR. Lower it if a line is ever missed; 0
  reads every frame. A line's translation is requested the first time it
  is seen and shown once a second frame confirms it, so the answer is
  usually there by then.
- **Keep the overlay out of recordings** (Game page): off by default, so
  recordings, streams and screenshots include the translations. Turn it
  on if a capture tool should not see the overlay.
- **Write the cache every** (Advanced page, `--autosave-seconds`, default
  10 s): how soon new translations reach the cache file.

## Command line

`gametl --window "Part of the title" --translator deepl` runs on that
window without the tray; `--profile NAME` loads a profile first;
`--tray --window ...` runs with the tray and starts at once;
`--save-profile NAME` saves the resulting settings; `--debug` outlines
every tracked block and prints per-frame timings; `--list-windows` lists
the capturable windows. Options given on the command line override the
profile, or the defaults.

## Rendering a demo

Window-capture recorders (Xbox Game Bar, OBS "Game Capture") record the
game window only, so the overlay, a separate window, is not in the
recording even when it is on screen. Use a display capture (OBS "Display
Capture") to record both, or render the overlay onto an existing recording
with the same pipeline the app uses:

```
uv run python scripts/render_demo.py capture.mp4 --start 508 --end 520 --out docs/demo.gif
```

This is also a way to try a game from a recording without running it.

## Architecture

One frame goes through these steps, about ten times a second, on the
pipeline thread (`app/pipeline.py`):

1. `capture/` grabs the game window with Windows Graphics Capture and
   hands over a BGR frame.
2. `ocr/` reads the selected area (or the whole client area) with
   RapidOCR's PP-OCR models on ONNX Runtime and returns text lines with
   pixel boxes. A frame in whose area nothing has changed since the last
   one read (judged on a small grey thumbnail) and whose blocks are all
   settled is not read at all.
3. `tracking/filters.py` drops lines in ignore zones or matching ignore
   patterns; `tracking/blocks.py` groups lines into blocks and matches them
   to the blocks seen in earlier frames, so each block keeps its id, a
   stability count and a few frames of grace when OCR misses it.
4. `translate/service.py` answers from the per-game cache at once and sends
   new text to the translator on a worker thread (with an optional faster
   draft translator); the pipeline never waits for a reply. New
   translations are written to the cache file within seconds; a cache file
   that cannot be read is set aside as `.bad` and the game starts with an
   empty one.
5. `layout/` decides how a translation is drawn: `style.py` keeps size and
   colours consistent (per band in place; one locked style for the whole
   subtitle zone), `fit.py` wraps and sizes text, `colors.py` samples the
   background and text colours.
6. `overlay/paint.py` paints the result (fonts, layouts; one
   painter shared with the settings preview and the demo renderer) and
   `overlay/window.py` shows it in a click-through window glued to the
   game, in subtitle mode or in place.

`app/controller.py` builds this chain from a `Settings` object and owns it
while it runs; the tray icon, the settings window and the command line are
the three ways of driving it. The slow part of a start (waiting for the
window, loading or downloading models) runs on a thread, so the tray and
the settings window stay responsive. Settings edited while a session runs
reach the pipeline and the overlay directly; a change of window, language
or translator restarts the session.

The settings window is Qt Quick, drawn by its software renderer (a form
needs no GPU, and a Direct3D window opening beside a game can make a
display flicker). The pages are QML files under `app/qml/`, styled by hand
(`Theme.qml` holds the colours and sizes); `app/settings_backend.py` is
what they read and write: a property map with one entry per setting, plus
the actions (start, select an area, save a key, activate a licence) that
go to the tray as signals.

```
src/gametl/
  capture/    window-targeted screen capture (Windows Graphics Capture)
  ocr/        text detection and recognition (RapidOCR on ONNX Runtime)
  tracking/   lines -> blocks, cross-frame matching, stability gate, ignore filters
  translate/  Translator interface, Claude / DeepL / offline backends, cache, service
  layout/     fitting text into the source box, colour sampling, consistent styling
  overlay/    block painter, transparent click-through window, area selector
  app/        controller, pipeline thread, tray icon, settings window (qml/), hotkeys, profiles, API keys
scripts/      fake game, demo renderer, diagnostics, build, model conversion, settings-window renders
tests/
docs/         demo clip, renders of the settings pages (docs/ui)
```

[PLAN.md](PLAN.md) records the design decisions and the measurements
behind them.

## Development

```
uv run pytest
uv run ruff check src tests scripts
uv run ruff format src tests scripts
```

The overlay, selector and hotkey tests need an interactive desktop
session; CI skips them.

- `scripts/fake_game.py` opens a stand-in game window with a HUD and a
  large subtitle that changes every few seconds, so the whole pipeline can
  be tried without a game and without API calls:

  ```
  uv run python scripts/fake_game.py
  uv run gametl --window "Fake Game" --translator verbose --roi 0,0.75,1,0.25
  ```

- `scripts/preview_ui.py --full --out out/ui` renders every settings page
  to PNG without a display (the renders in `docs/ui` come from it);
  `gametl --check-ui` loads every page offscreen and reports QML problems.
  CI runs the latter from the frozen build too.
- `scripts/spike_capture_ocr.py` captures a window and prints what OCR
  sees, with timings, without the overlay.
- `scripts/bench_translate.py` measures Claude request latency per
  configuration (real API calls).
- `scripts/make_license.py` issues licence keys; it needs the private
  signing key, which is not in the repository.

## Releases

```
uv run --group build python scripts/build.py
```

builds the distributable folder `dist/gametl` with PyInstaller. GitHub
Actions (`.github/workflows/release.yml`) does the same on a Windows
runner: bump `version` in `pyproject.toml` and merge to `main`, and the
workflow, seeing a version with no tag yet, builds the folder, creates the
tag `v<version>` at the merge commit and attaches
`gametl-v<version>-win64.zip` to its release. A merge whose version is
already tagged builds nothing. Pushing a tag by hand (a dash, as in
`v0.2.0-beta1`, makes a pre-release) or running the workflow from the
Actions tab with a tag name does the same; with the tag left empty, the
workflow builds without releasing and keeps the zip as a seven-day
artifact. The tag must match the `pyproject.toml` version.

The releases of a private repository are visible to its collaborators
only; for customers, publish the zip elsewhere. The executables are not
code-signed, so Windows warns about an unknown publisher until a signing
step is added.

## Acknowledgements

[RapidOCR](https://github.com/RapidAI/RapidOCR) and the PP-OCR models,
[ONNX Runtime](https://onnxruntime.ai/),
[windows-capture](https://github.com/NiiightmareXD/windows-capture),
[CTranslate2](https://github.com/OpenNMT/CTranslate2) with the
[OPUS-MT](https://github.com/Helsinki-NLP/Opus-MT) and
[Argos Translate](https://github.com/argosopentech/argos-translate) models,
[PySide6](https://doc.qt.io/qtforpython-6/), and the DeepL and Anthropic
APIs.

## Licensing

Subline (gametl) is proprietary software, copyright (c) 2026 Mustafa
Yurdakul. It may be used for a 14-day trial, after which a licence key
bought from the author is required; see [LICENSE](LICENSE) for the terms.
The open-source components it bundles or downloads are listed with their
licences in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Licence
enquiries: mustafa@yurdakul.dev.
