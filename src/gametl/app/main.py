"""Command-line entry point.

  gametl                                   # tray icon, with the profile of the game that is open
                                           # (or the last one used); settings open unless it runs
  gametl --window "Fake Game"              # run on that window from the command line
  gametl --profile fake-game               # run with a saved profile
  gametl --tray --window "Fake Game"       # tray icon and start at once
  gametl --window "Fake Game" --save-profile "Fake Game"   # save these options as a profile
  gametl pretranslate script.txt --game "Fake Game"        # same as gametl-pretranslate

Options given on the command line override the profile (or the defaults).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from gametl.app.config import ProfileStore, Settings, slug

if TYPE_CHECKING:  # imported where it runs: Qt loads only when a window or an overlay is wanted
    from gametl.app.controller import OverlayController


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_argument_group("mode")
    mode.add_argument("--tray", action="store_true", help="run with a tray icon (default when no window is given)")
    mode.add_argument("--list-windows", action="store_true", help="list capturable windows and exit")
    mode.add_argument("--profile", help="load this saved profile first")
    mode.add_argument("--save-profile", metavar="NAME", help="save the resulting settings as a profile and continue")
    mode.add_argument("--data-dir", help="where profiles and caches live (default %%APPDATA%%\\gametl)")
    mode.add_argument(
        "--download-model",
        action="store_true",
        help="download the offline translator (its runtime, once) and the model for the language pair, then exit",
    )
    mode.add_argument(
        "--remove-all-data",
        action="store_true",
        help="delete the data folder and the Credential Manager entries (the API keys) and exit",
    )
    mode.add_argument(
        "--check-ui", action="store_true", help="load every settings page without a display, report problems and exit"
    )

    target = p.add_argument_group("target")
    target.add_argument("--window", help="title substring of the game window")
    target.add_argument("--hwnd", help="window handle (decimal or 0x hex)")
    target.add_argument("--wait", type=float, default=10.0, help="seconds to wait for the window to appear")
    target.add_argument(
        "--roi",
        help="the only area to read and translate: x,y,w,h as fractions or pixels of the client area "
        f"(default {Settings.roi}, the bottom quarter; empty = the whole area)",
    )
    target.add_argument(
        "--include-frame", action="store_true", default=None, help="also read the title bar / window frame"
    )

    lang = p.add_argument_group("languages")
    lang.add_argument("--lang", help=f"OCR model language (en, ch, japan, korean, de, ...); default {Settings.lang}")
    lang.add_argument(
        "--source-lang", help="what the translator is told the text is in; default: the OCR language (--lang)"
    )
    lang.add_argument("--target-lang", help=f"target language code; default {Settings.target_lang}")
    lang.add_argument("--ocr-gpu", action="store_true", default=None, help="run OCR on the GPU (DirectML)")

    tr = p.add_argument_group("translation")
    tr.add_argument("--translator", choices=["claude", "deepl", "offline", "uppercase", "echo", "verbose"])
    tr.add_argument(
        "--draft", choices=["none", "offline", "deepl"], help="fast draft shown until the translator answers"
    )
    tr.add_argument("--model", help=f"default {Settings.model}")
    tr.add_argument("--effort", choices=["low", "medium", "high"])
    tr.add_argument("--thinking", choices=["disabled", "adaptive"])
    tr.add_argument("--structured", action="store_true", default=None, help="server-side structured output")
    tr.add_argument("--game", help="game name for the prompt and the cache file; default: window title")
    tr.add_argument("--glossary", help='JSON file {"term": "translation"}')
    tr.add_argument("--tone", help="notes for the translator on tone and formality")
    tr.add_argument("--no-cache-file", action="store_true", default=None, help="keep the cache in memory only")

    look = p.add_argument_group("appearance and ignores")
    look.add_argument(
        "--render",
        choices=["subtitle", "chat", "inplace"],
        help="with an area: one fixed subtitle style centred in it (default), the last lines as a chat transcript "
        "in a corner, or per-block at the OCR box",
    )
    look.add_argument("--chat-lines", type=int, metavar="N", help=f"chat: lines kept (default {Settings.chat_lines})")
    look.add_argument(
        "--chat-seconds",
        type=int,
        metavar="S",
        help=f"chat: a line leaves this long after it was said; 0 = never (default {Settings.chat_seconds})",
    )
    look.add_argument("--chat-corner", choices=["bottom-left", "bottom-right", "top-left", "top-right"])
    look.add_argument("--chat-width", type=int, metavar="%", help=f"chat: card width (default {Settings.chat_width})")
    look.add_argument(
        "--subtitle-font", type=int, metavar="PX", help="fixed subtitle font size; 0 = the game's own size"
    )
    look.add_argument(
        "--subtitle-color", metavar="#RRGGBB", help="subtitle text colour; empty (default) = the game's own colour"
    )
    look.add_argument(
        "--subtitle-background", choices=["pill", "shadow", "none"], help=f"default {Settings.subtitle_background}"
    )
    look.add_argument(
        "--subtitle-pill-alpha",
        type=int,
        metavar="0-255",
        help=f"opacity of the pill (default {Settings.subtitle_pill_alpha})",
    )
    look.add_argument("--subtitle-weight", choices=["regular", "medium", "semibold", "bold"])
    look.add_argument(
        "--subtitle-position", choices=["bottom", "source", "center"], help="default bottom (steady baseline)"
    )
    look.add_argument(
        "--subtitle-center-tolerance",
        type=int,
        metavar="PCT",
        help="drop text whose centre is further than PCT%% of the area width from its centre "
        f"(default {Settings.subtitle_center_tolerance}; 0 = off)",
    )
    look.add_argument(
        "--subtitle-size-tolerance",
        type=int,
        metavar="PCT",
        help="drop text whose line height differs more than PCT%% from the learned subtitle size "
        f"(default {Settings.subtitle_size_tolerance}; 0 = off)",
    )
    look.add_argument(
        "--short-line-confidence",
        type=float,
        metavar="0-1",
        help="a line of one or two letters needs this OCR confidence "
        f"(default {Settings.short_line_confidence}; 0 = off)",
    )
    look.add_argument(
        "--hide-source",
        action="store_true",
        default=None,
        help="cover the original line when the subtitle is drawn elsewhere",
    )
    look.add_argument(
        "--no-center-area",
        action="store_true",
        default=None,
        help="do not mirror a selected area about the centre by default (Shift while dragging inverts either way)",
    )
    # The option's name before center_zone became center_area, kept for existing shortcuts and scripts.
    look.add_argument(
        "--no-center-zone", dest="no_center_area", action="store_true", default=None, help=argparse.SUPPRESS
    )
    look.add_argument("--style", choices=["auto", "patch", "pill", "outline"], help="in-place style")
    look.add_argument("--font")
    look.add_argument("--ignore", action="append", metavar="x,y,w,h", help="zone never to translate; repeatable")
    look.add_argument("--ignore-pattern", action="append", metavar="REGEX", help="drop OCR lines matching; repeatable")

    run = p.add_argument_group("pipeline")
    run.add_argument("--fps", type=float, help=f"capture cap; default {Settings.fps:g}")
    run.add_argument(
        "--full-scan-every",
        type=int,
        help="with --roi and --render inplace: also sweep the rest every N OCR reads (default 0 = never)",
    )
    run.add_argument("--stable-frames", type=int)
    run.add_argument("--max-missing", type=int)
    run.add_argument(
        "--change-threshold",
        type=float,
        metavar="N",
        help="read the area again once something in it changes by N "
        f"(the strongest local change in a small thumbnail, 0-255; default {Settings.change_threshold:g}; "
        "0 = every frame)",
    )
    run.add_argument(
        "--autosave-seconds",
        type=float,
        metavar="S",
        help=f"write new translations to the cache file within S seconds (default {Settings.autosave_seconds:g})",
    )
    run.add_argument(
        "--no-hide-unfocused",
        action="store_true",
        default=None,
        help="keep the overlay up when the game is not in front",
    )
    run.add_argument(
        "--exclude-from-capture",
        action="store_true",
        default=None,
        help="keep the overlay out of screen recordings, streams and screenshots",
    )
    run.add_argument("--run-for", type=float, default=0.0, help="quit after N seconds (0 = until the window closes)")
    run.add_argument("--screenshot", help="with --run-for: save a screenshot of the game area before quitting")
    run.add_argument(
        "--debug", action="store_true", default=None, help="outline every tracked block and print per-frame stats"
    )
    run.add_argument("--dump-dir", help="debug: save every captured frame with OCR lines and blocks drawn")
    return p


# Command-line option -> Settings field, copied when the option was given.
# Most options are named after their field; three are not.
_VALUE_OPTIONS = {
    name: name
    for name in (
        "roi", "lang", "source_lang", "target_lang", "translator", "model", "effort", "thinking", "game", "tone",
        "style", "font", "fps", "full_scan_every", "stable_frames", "max_missing", "change_threshold",
        "autosave_seconds", "render", "subtitle_color", "subtitle_background", "subtitle_pill_alpha",
        "subtitle_position", "subtitle_center_tolerance", "subtitle_size_tolerance", "short_line_confidence",
        "subtitle_weight", "chat_lines", "chat_seconds", "chat_corner", "chat_width", "dump_dir",
    )
} | {"window": "window_match", "glossary": "glossary_path", "subtitle_font": "subtitle_font_px"}  # fmt: skip
# Flag -> (Settings field, value it sets); the flag's absence leaves the profile's value alone.
_FLAG_OPTIONS = {
    "no_center_area": ("center_area", False),
    "hide_source": ("subtitle_hide_source", True),
    "include_frame": ("include_frame", True),
    "structured": ("structured", True),
    "no_cache_file": ("use_cache_file", False),
    "no_hide_unfocused": ("hide_when_unfocused", False),
    "exclude_from_capture": ("exclude_from_capture", True),
    "debug": ("debug", True),
    "ocr_gpu": ("ocr_gpu", True),
}


def settings_from_args(args: argparse.Namespace, base: Settings) -> Settings:
    """Overlay the command-line options that were given on `base`."""
    s = base.copy()
    for option, attr in _VALUE_OPTIONS.items():
        value = getattr(args, option)
        if value is not None:
            setattr(s, attr, value)
    for flag, (attr, value) in _FLAG_OPTIONS.items():
        if getattr(args, flag, None) is not None:
            setattr(s, attr, value)
    if args.draft is not None:
        s.draft = "" if args.draft == "none" else args.draft
    if args.ignore:
        s.ignore_zones = list(args.ignore)
    if args.ignore_pattern:
        s.ignore_patterns = list(args.ignore_pattern)
    return s


def screenshot(rect: tuple[int, int, int, int], path: str) -> None:
    """Save a screen rectangle, layered windows (the overlay) included."""
    from PIL import ImageGrab

    image = ImageGrab.grab(bbox=rect, include_layered_windows=True, all_screens=True)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    image.save(path)


def utf8_console() -> None:
    """Status lines may contain the target language: never die on a cp1252
    console. A windowed build has no console at all: write to a log file in
    the data folder instead. Either way, a native crash (access violation
    in a DLL) dumps the Python stacks of all threads to the same place."""
    import faulthandler

    if sys.stdout is None or sys.stderr is None:
        from gametl.app.config import app_dir

        log_dir = app_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "gametl.log"
        mode = "w" if log_path.exists() and log_path.stat().st_size > 5_000_000 else "a"
        log = open(log_path, mode, encoding="utf-8", buffering=1)  # noqa: SIM115 (stays open for the process)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
        faulthandler.enable(file=log, all_threads=True)
        from gametl.app.cleanup import register_log

        register_log(log)  # "Remove all data" closes it before deleting the folder
        return
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    with contextlib.suppress(AttributeError, OSError, ValueError):
        faulthandler.enable(all_threads=True)


def open_window_titles() -> list[str]:
    """Titles of the windows open now; none when they cannot be listed."""
    from gametl.capture.windows import list_windows

    try:
        return [w.title for w in list_windows()]
    except Exception:  # no desktop session: carry on with the last profile
        return []


def show_settings_if_start_fails(controller: OverlayController, open_settings: Callable[[], None]) -> None:
    """Open the settings when the start under way fails, so its reason
    (a missing key, no matching window, the OCR model) is seen: a tray app started
    without its window has only the tray's tooltip to show it in. Only that
    one start: once it runs or is given up, later failures stay in the tray."""

    def settle(failed: bool) -> None:
        controller.start_failed.disconnect(on_failed)
        controller.running_changed.disconnect(on_running_changed)
        if failed:
            open_settings()

    def on_failed(_message: str) -> None:
        settle(True)

    def on_running_changed(_running: bool) -> None:
        settle(False)

    controller.start_failed.connect(on_failed)
    controller.running_changed.connect(on_running_changed)


def main(argv: list[str] | None = None) -> int:
    utf8_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "pretranslate":  # one executable, two tools: `gametl pretranslate ...`
        from gametl.app.pretranslate import main as pretranslate_main

        return pretranslate_main(argv[1:])
    args = build_parser().parse_args(argv)
    if args.check_ui:
        from gametl.app.settings_window import check

        problems = check()
        print("\n".join([*problems, f"settings window: {len(problems)} problems"]))
        return 1 if problems else 0

    # Physical pixels everywhere: overlay geometry == capture-frame pixels.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    from gametl.capture.windows import enable_per_monitor_dpi_awareness, list_windows

    enable_per_monitor_dpi_awareness()

    if args.list_windows:
        for w in sorted(list_windows(), key=lambda w: w.title.casefold()):
            print(f"0x{w.hwnd:08X} {w.width:5d}x{w.height:<5d} [{w.class_name}] {w.title}")
        return 0

    try:
        hwnd = int(args.hwnd, 0) if args.hwnd else None
    except ValueError:
        print(f"--hwnd {args.hwnd!r} is not a window handle (decimal or 0x hex)")
        return 2

    store = ProfileStore(args.data_dir)
    if args.remove_all_data:
        from gametl.app.cleanup import remove_all_data
        from gametl.app.credentials import WindowsCredentialStore

        report = remove_all_data(store, WindowsCredentialStore())
        print(report.text)
        return 0 if report.complete else 1
    profile_name = args.profile
    if profile_name:
        if not store.exists(profile_name):
            print(f"no profile named {profile_name!r}; saved profiles: {', '.join(store.list()) or 'none'}")
            return 2
        base = store.load(profile_name)
        profile_name = slug(profile_name)
    else:
        base = Settings()
    settings = settings_from_args(args, base)

    if args.save_profile:
        path = store.save(args.save_profile, settings)
        profile_name = store.last_profile = slug(args.save_profile)
        print(f"profile saved to {path}")

    if args.download_model:
        from gametl.translate.offline import ensure_offline

        try:
            model_dir = ensure_offline(
                settings.effective_source_lang, settings.target_lang, store.models_dir, store.runtime_dir, print
            )
        except Exception as exc:
            print(f"download failed: {exc}")
            return 2
        print(f"offline translation ready: {model_dir}")
        return 0

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from gametl.app.cleanup import forget_trial
    from gametl.app.controller import OverlayController

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    controller = OverlayController(store)
    forget_trial(store, controller.secrets)  # what 0.2.x left behind
    controller.status.connect(lambda s: print(s, flush=True))

    tray_mode = args.tray or (not settings.window_match and hwnd is None)
    start_now = bool(settings.window_match or hwnd)
    instance = None

    if tray_mode:
        from gametl import APP_NAME
        from gametl.app.tray import SingleInstance, TrayApp

        instance = SingleInstance(store.root)
        if not instance.claim(lambda: tray.open_settings()):
            print(f"{APP_NAME} is already running: its settings window was brought up")
            return 0
        if not (args.profile or args.window or hwnd):
            # Plain `gametl`: carry on with the game that is open, or the one played last.
            # Only a game found running starts at once; otherwise the settings show its profile.
            remembered = store.remembered_profile(open_window_titles())
            if remembered is not None:
                profile_name, base, start_now = remembered
                settings = settings_from_args(args, base)
                if store.last_profile != profile_name:
                    store.last_profile = profile_name
        tray = TrayApp(app, controller, store, settings, profile_name)
        if start_now:
            if not (args.profile or args.window or hwnd):
                # Started on its own, with no window open: a failure must not go unseen (no key, no window...).
                show_settings_if_start_fails(controller, tray.open_settings)
            controller.start(settings, hwnd, wait=args.wait)
        else:
            tray.open_settings()
    else:
        controller.start(settings, hwnd, wait=args.wait)
        # The session starts on a thread: a failure to start, or the end of
        # the session (window closed, pipeline error), ends the process.
        controller.start_failed.connect(lambda _message: app.exit(2))
        controller.running_changed.connect(lambda running: None if running else app.quit())

    if args.run_for:

        def finish() -> None:
            if args.screenshot and controller.overlay and controller.overlay.target_rect:
                screenshot(controller.overlay.target_rect, args.screenshot)
                print(f"screenshot saved to {args.screenshot}")
            app.quit()

        QTimer.singleShot(int(args.run_for * 1000), finish)

    rc = app.exec()
    controller.close()  # a no-op when the session has ended already (the tray's Quit, a closed window)
    if instance is not None:
        instance.release()
    if controller.last_stats:
        print(controller.last_stats)
    return rc


if __name__ == "__main__":
    sys.exit(main())
