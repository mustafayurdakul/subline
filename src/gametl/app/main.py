"""Command-line entry point.

  gametl                                   # tray icon; opens settings if nothing is configured
  gametl --window "Fake Game"              # run on that window from the command line
  gametl --profile fake-game               # run with a saved profile
  gametl --tray --window "Fake Game"       # tray icon and start at once
  gametl --window "Fake Game" --save-profile "Fake Game"   # save these options as a profile
  gametl pretranslate script.txt --game "Fake Game"        # same as gametl-pretranslate

Options given on the command line override the profile (or the defaults).
"""

from __future__ import annotations

import argparse
import os
import sys

from gametl.app.config import ProfileStore, Settings, slug


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_argument_group("mode")
    mode.add_argument("--tray", action="store_true", help="run with a tray icon (default when no window is given)")
    mode.add_argument("--list-windows", action="store_true", help="list capturable windows and exit")
    mode.add_argument("--profile", help="load this saved profile first")
    mode.add_argument("--save-profile", metavar="NAME", help="save the resulting settings as a profile and continue")
    mode.add_argument("--data-dir", help="where profiles and caches live (default %%APPDATA%%\\gametl)")
    mode.add_argument("--download-model", action="store_true",
                      help="download the offline model for the language pair and exit")

    target = p.add_argument_group("target")
    target.add_argument("--window", help="title substring of the game window")
    target.add_argument("--hwnd", help="window handle (decimal or 0x hex)")
    target.add_argument("--wait", type=float, default=10.0, help="seconds to wait for the window to appear")
    target.add_argument("--roi", help="the only area to read and translate: x,y,w,h as fractions or pixels of the client area")
    target.add_argument("--include-frame", action="store_true", default=None, help="also read the title bar / window frame")

    lang = p.add_argument_group("languages")
    lang.add_argument("--lang", help="OCR model language (en, ch, japan, korean, de, ...); default en")
    lang.add_argument("--source-lang", help="source language for the translator; default: same as --lang")
    lang.add_argument("--target-lang", help="target language code; default tr")

    tr = p.add_argument_group("translation")
    tr.add_argument("--translator", choices=["claude", "offline", "uppercase", "echo", "verbose"])
    tr.add_argument("--draft", choices=["none", "offline"], help="instant offline draft until the translator answers")
    tr.add_argument("--model", help="default claude-haiku-5-5")
    tr.add_argument("--effort", choices=["low", "medium", "high"])
    tr.add_argument("--thinking", choices=["disabled", "adaptive"])
    tr.add_argument("--structured", action="store_true", default=None, help="server-side structured output")
    tr.add_argument("--game", help="game name for the prompt and the cache file; default: window title")
    tr.add_argument("--glossary", help="JSON file {\"term\": \"translation\"}")
    tr.add_argument("--tone", help="notes for the translator on tone and formality")
    tr.add_argument("--no-cache-file", action="store_true", default=None, help="keep the cache in memory only")

    look = p.add_argument_group("appearance and ignores")
    look.add_argument("--style", choices=["auto", "patch", "pill", "outline"])
    look.add_argument("--font")
    look.add_argument("--ignore", action="append", metavar="x,y,w,h", help="zone never to translate; repeatable")
    look.add_argument("--ignore-pattern", action="append", metavar="REGEX", help="drop OCR lines matching; repeatable")

    run = p.add_argument_group("pipeline")
    run.add_argument("--fps", type=float, help="capture cap; default 10")
    run.add_argument("--full-scan-every", type=int, help="with --roi: also sweep the rest every N frames (default 0 = never)")
    run.add_argument("--stable-frames", type=int)
    run.add_argument("--max-missing", type=int)
    run.add_argument("--no-hide-unfocused", action="store_true", default=None, help="keep the overlay up when the game is not in front")
    run.add_argument("--capturable", action="store_true", default=None, help="do not exclude the overlay from screen capture")
    run.add_argument("--run-for", type=float, default=0.0, help="quit after N seconds (0 = until the window closes)")
    run.add_argument("--screenshot", help="with --run-for: save a screenshot of the game area before quitting")
    run.add_argument("--debug", action="store_true", default=None, help="outline every tracked block and print per-frame stats")
    run.add_argument("--dump-dir", help="debug: save every captured frame with OCR lines and blocks drawn")
    return p


def settings_from_args(args: argparse.Namespace, base: Settings) -> Settings:
    """Overlay explicit command-line options on `base`."""
    s = base.copy()
    direct = {
        "window": "window_match", "roi": "roi", "lang": "lang", "source_lang": "source_lang",
        "target_lang": "target_lang", "translator": "translator", "model": "model", "effort": "effort",
        "thinking": "thinking", "game": "game", "glossary": "glossary_path", "tone": "tone",
        "style": "style", "font": "font", "fps": "fps", "full_scan_every": "full_scan_every",
        "stable_frames": "stable_frames", "max_missing": "max_missing",
    }
    for arg, attr in direct.items():
        value = getattr(args, arg, None)
        if value is not None:
            setattr(s, attr, value)
    if args.draft is not None:
        s.draft = "" if args.draft == "none" else args.draft
    if args.include_frame is not None:
        s.include_frame = True
    if args.structured is not None:
        s.structured = True
    if args.no_cache_file is not None:
        s.use_cache_file = False
    if args.no_hide_unfocused is not None:
        s.hide_when_unfocused = False
    if args.capturable is not None:
        s.exclude_from_capture = False
    if args.ignore:
        s.ignore_zones = list(args.ignore)
    if args.ignore_pattern:
        s.ignore_patterns = list(args.ignore_pattern)
    if args.debug is not None:
        s.debug = True
    if args.dump_dir:
        s.dump_dir = args.dump_dir
    return s


def utf8_console() -> None:
    """Status lines may contain the target language; never die on a cp1252
    console. A windowed build has no console at all: write to a log file in
    the data folder instead."""
    if sys.stdout is None or sys.stderr is None:
        from gametl.app.config import app_dir

        log_dir = app_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "gametl.log"
        mode = "w" if log_path.exists() and log_path.stat().st_size > 5_000_000 else "a"
        log = open(log_path, mode, encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    utf8_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "pretranslate":  # one executable, two tools: `gametl pretranslate ...`
        from gametl.app.pretranslate import main as pretranslate_main

        return pretranslate_main(argv[1:])
    args = build_parser().parse_args(argv)

    # Physical pixels everywhere: overlay geometry == capture-frame pixels.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    from gametl.capture.windows import enable_per_monitor_dpi_awareness, list_windows

    enable_per_monitor_dpi_awareness()

    if args.list_windows:
        for w in sorted(list_windows(), key=lambda w: w.title.casefold()):
            print(f"0x{w.hwnd:08X} {w.width:5d}x{w.height:<5d} [{w.class_name}] {w.title}")
        return 0

    store = ProfileStore(args.data_dir)
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
        store.last_profile = slug(args.save_profile)
        profile_name = slug(args.save_profile)
        print(f"profile saved to {path}")

    if args.download_model:
        from gametl.translate.offline import ensure_model

        try:
            model_dir, sp = ensure_model(settings.effective_source_lang, settings.target_lang, store.models_dir, print)
        except Exception as exc:
            print(f"download failed: {exc}")
            return 2
        print(f"offline model ready: {model_dir}")
        return 0

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from gametl.app.controller import OverlayController, grab_screen_region

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    controller = OverlayController(store)
    controller.status.connect(lambda s: print(s, flush=True))

    hwnd = int(args.hwnd, 0) if args.hwnd else None
    tray_mode = args.tray or (not settings.window_match and hwnd is None)

    if tray_mode:
        from gametl.app.tray import TrayApp

        tray = TrayApp(app, controller, store, settings, profile_name)
        if settings.window_match or hwnd:
            controller.start(settings, hwnd, wait=args.wait)
        else:
            tray.open_settings()
    else:
        if not controller.start(settings, hwnd, wait=args.wait):
            return 2
        controller.running_changed.connect(lambda running: None if running else app.quit())

    if args.run_for:

        def finish() -> None:
            if args.screenshot and controller.overlay and controller.overlay.target_rect:
                grab_screen_region(controller.overlay.target_rect, args.screenshot)
                print(f"screenshot saved to {args.screenshot}")
            app.quit()

        QTimer.singleShot(int(args.run_for * 1000), finish)

    rc = app.exec()
    stats = controller.stats_text()
    controller.stop()
    if stats:
        print(stats)
    return rc


if __name__ == "__main__":
    sys.exit(main())
