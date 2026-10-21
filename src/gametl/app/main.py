"""Command-line entry point: overlay a window with translated text.

  gametl --window "Fake Game"                       # English -> Turkish with Claude
  gametl --window "Fake Game" --roi 0,0.75,1,0.25   # subtitle strip at full rate
  gametl --window "Fake Game" --translator uppercase --debug
  gametl --window "Fake Game" --run-for 8 --screenshot out/overlay.png
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


def parse_roi(spec: str | None, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not spec:
        return None
    x, y, w, h = (float(v) for v in spec.split(","))
    if max(x, y, w, h) <= 1.0:
        x, y, w, h = x * width, y * height, w * width, h * height
    return max(0, int(x)), max(0, int(y)), min(width, int(x + w)), min(height, int(y + h))


def grab_screen_region(rect: tuple[int, int, int, int], path: str) -> None:
    """Screenshot of a screen rectangle including layered windows (ours)."""
    from PIL import ImageGrab

    image = ImageGrab.grab(bbox=rect, include_layered_windows=True, all_screens=True)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    image.save(path)


def default_cache_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "gametl" / "cache"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "game"


def ensure_anthropic_credentials() -> bool:
    """True when the SDK will find credentials. Also picks up a key set in the
    Windows user environment after this process started."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "ANTHROPIC_API_KEY")
            if value:
                os.environ["ANTHROPIC_API_KEY"] = str(value)
                return True
    except OSError:
        pass
    profile_dir = Path.home() / ".config" / "anthropic"
    return profile_dir.exists()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--window", help="title substring of the game window")
    target.add_argument("--hwnd", help="window handle (decimal or 0x hex)")
    p.add_argument("--wait", type=float, default=10.0, help="seconds to wait for the window to appear")
    p.add_argument("--roi", help="subtitle zone x,y,w,h as fractions or pixels of the client area; default all of it")
    p.add_argument("--include-frame", action="store_true", help="also read the title bar / window frame (default: client area only)")

    lang = p.add_argument_group("languages")
    lang.add_argument("--lang", default="en", help="OCR model language (en, ch, japan, korean, de, ...)")
    lang.add_argument("--source-lang", help="source language for the translator; default: same as --lang")
    lang.add_argument("--target-lang", default="tr", help="target language code (default tr)")

    tr = p.add_argument_group("translation")
    tr.add_argument("--translator", choices=["claude", "uppercase", "echo"], default="claude")
    tr.add_argument("--model", default="claude-haiku-5-5")
    tr.add_argument("--effort", default="low", choices=["low", "medium", "high"])
    tr.add_argument("--no-thinking", action="store_true", help="send thinking=disabled (works at effort <= high)")
    tr.add_argument("--game", help="game name for the prompt and the cache file; default: window title")
    tr.add_argument("--glossary", help="JSON file {\"term\": \"translation\"} of names/terms to render consistently")
    tr.add_argument("--style", help="free-text style notes for the translator (tone, formality)")
    tr.add_argument("--cache-dir", help="where per-game translation caches live (default %%APPDATA%%\\gametl\\cache)")
    tr.add_argument("--no-cache-file", action="store_true", help="keep the cache in memory only")

    run = p.add_argument_group("pipeline")
    run.add_argument("--fps", type=float, default=10.0, help="capture cap")
    run.add_argument("--full-scan-every", type=int, default=10, help="with --roi: full-area scan every N frames")
    run.add_argument("--stable-frames", type=int, default=1)
    run.add_argument("--max-missing", type=int, default=3)
    run.add_argument("--font", default="Segoe UI")
    run.add_argument("--no-hide-unfocused", action="store_true", help="keep the overlay up when the game is not in front")
    run.add_argument("--capturable", action="store_true", help="do not exclude the overlay from screen capture")
    run.add_argument("--debug", action="store_true", help="outline every tracked block and print per-frame stats")
    run.add_argument("--dump-dir", help="debug: save every captured frame with OCR lines and blocks drawn")
    run.add_argument("--run-for", type=float, default=0.0, help="quit after N seconds (0 = until the window closes)")
    run.add_argument("--screenshot", help="with --run-for: save a screenshot of the game area before quitting")
    args = p.parse_args(argv)

    # Physical pixels everywhere: overlay geometry == capture-frame pixels.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

    from gametl.capture.windows import (
        client_rect_on_screen,
        enable_per_monitor_dpi_awareness,
        find_window,
        window_rect,
    )

    enable_per_monitor_dpi_awareness()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from gametl.app.pipeline import PipelineConfig, PipelineThread
    from gametl.ocr.rapid import RapidOcrEngine
    from gametl.overlay.window import OverlayWindow
    from gametl.translate.cache import TranslationCache
    from gametl.translate.dummy import EchoTranslator, UppercaseTranslator
    from gametl.translate.service import TranslationService

    app = QApplication(sys.argv[:1])

    # -- target window ---------------------------------------------------------
    title = args.window or ""
    if args.hwnd:
        hwnd = int(args.hwnd, 0)
    else:
        deadline = time.perf_counter() + args.wait
        info = find_window(args.window)
        while info is None and time.perf_counter() < deadline:
            time.sleep(0.5)
            info = find_window(args.window)
        if info is None:
            print(f"no visible window with title containing {args.window!r}")
            return 2
        hwnd, title = info.hwnd, info.title
        print(f"target: {info.title!r} hwnd=0x{hwnd:X} rect={info.rect}")

    rect = window_rect(hwnd)
    frame_w, frame_h = rect[2] - rect[0], rect[3] - rect[1]
    # The capture frame covers the DWM bounds (title bar included on a normal
    # window). By default only the client area, where the game draws, is read.
    area: tuple[int, int, int, int] | None = None
    if not args.include_frame:
        c = client_rect_on_screen(hwnd)
        area = (
            max(0, c[0] - rect[0]),
            max(0, c[1] - rect[1]),
            min(frame_w, c[2] - rect[0]),
            min(frame_h, c[3] - rect[1]),
        )
        if area[2] <= area[0] or area[3] <= area[1]:
            area = None
    ax0, ay0, ax1, ay1 = area or (0, 0, frame_w, frame_h)
    roi = parse_roi(args.roi, ax1 - ax0, ay1 - ay0)
    if roi is not None:
        roi = (roi[0] + ax0, roi[1] + ay0, roi[2] + ax0, roi[3] + ay0)
    print(f"frame {frame_w}x{frame_h}, area {area or 'whole frame'}, roi {roi or 'whole area'}")

    # -- translation -----------------------------------------------------------
    source_lang = args.source_lang or args.lang
    game = args.game or title or "game"
    if args.translator == "claude":
        if not ensure_anthropic_credentials():
            print(
                "No Anthropic credentials found. Set ANTHROPIC_API_KEY in your user environment "
                "variables (Windows: Settings > System > About > Advanced system settings > "
                "Environment Variables), or run with --translator uppercase to test without translation."
            )
            return 2
        from gametl.translate.claude import ClaudeTranslator

        glossary = None
        if args.glossary:
            with open(args.glossary, encoding="utf-8") as fh:
                glossary = json.load(fh)
        translator = ClaudeTranslator(
            model=args.model,
            effort=args.effort,
            thinking="disabled" if args.no_thinking else "adaptive",
            game=game,
            glossary=glossary,
            style=args.style,
            source_lang=source_lang,
            target_lang=args.target_lang,
        )
    elif args.translator == "uppercase":
        translator = UppercaseTranslator()
    else:
        translator = EchoTranslator()

    cache_path = None
    if not args.no_cache_file:
        cache_dir = Path(args.cache_dir) if args.cache_dir else default_cache_dir()
        cache_path = cache_dir / f"{slug(game)}.{args.target_lang}.{translator.name}.json"
    cache = TranslationCache(cache_path)
    print(f"translator: {translator.name}, {source_lang} -> {args.target_lang}, cache {cache_path or 'memory'} ({len(cache)} entries)")

    service = TranslationService(
        translator,
        cache,
        target_lang=args.target_lang,
        source_lang=source_lang,
        on_status=lambda s: print(s, flush=True),
    )

    # -- OCR, overlay, pipeline ---------------------------------------------------
    engine = RapidOcrEngine(lang=args.lang)
    print(f"OCR warm-up {engine.warm_up(frame_w, frame_h):.0f}ms")

    overlay = OverlayWindow(
        hwnd,
        hide_when_unfocused=not args.no_hide_unfocused,
        exclude_from_capture=not args.capturable,
        font_family=args.font,
    )
    config = PipelineConfig(
        area=area,
        roi=roi,
        fps=args.fps,
        full_scan_every=args.full_scan_every,
        stable_frames=args.stable_frames,
        max_missing=args.max_missing,
        debug=args.debug,
        dump_dir=args.dump_dir,
    )
    worker = PipelineThread(hwnd, engine, service, config)
    worker.blocks_ready.connect(overlay.set_blocks)
    worker.status.connect(lambda s: print(s, flush=True))
    overlay.target_lost.connect(app.quit)

    overlay.start()
    print(f"overlay up: ex_style=0x{overlay.ex_style():08X} excluded_from_capture={overlay.excluded_from_capture}")
    worker.start()

    if args.run_for:

        def finish() -> None:
            if args.screenshot and overlay.target_rect:
                grab_screen_region(overlay.target_rect, args.screenshot)
                print(f"screenshot saved to {args.screenshot}")
            app.quit()

        QTimer.singleShot(int(args.run_for * 1000), finish)

    rc = app.exec()
    worker.stop()
    worker.wait(3000)
    service.shutdown()
    if worker.ocr_ms:
        s = sorted(worker.ocr_ms)
        print(f"frames {worker.frames}, ocr median {s[len(s) // 2]:.0f}ms max {s[-1]:.0f}ms")
    st = service.stats
    print(
        f"translation: {st['requests']} requests, {st['items']} items sent, {st['translated']} translated, "
        f"{st['cache_hits']} cache hits, {st['errors']} errors; cache now {len(cache)} entries"
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
