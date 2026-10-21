"""Command-line entry point (M1): overlay a window with translated text.

  python -m gametl.app.main --window "Fake Game"
  python -m gametl.app.main --window "Fake Game" --roi 0,0.75,1,0.25 --debug
  python -m gametl.app.main --window "Fake Game" --run-for 8 --screenshot out/overlay.png
"""

from __future__ import annotations

import argparse
import os
import sys
import time


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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--window", help="title substring of the game window")
    target.add_argument("--hwnd", help="window handle (decimal or 0x hex)")
    p.add_argument("--wait", type=float, default=10.0, help="seconds to wait for the window to appear")
    p.add_argument("--roi", help="subtitle zone x,y,w,h as fractions or pixels of the client area; default all of it")
    p.add_argument("--include-frame", action="store_true", help="also read the title bar / window frame (default: client area only)")
    p.add_argument("--lang", default="en", help="OCR source language code")
    p.add_argument("--target-lang", default="en")
    p.add_argument("--translator", choices=["uppercase", "echo"], default="uppercase")
    p.add_argument("--fps", type=float, default=10.0, help="capture cap")
    p.add_argument("--full-scan-every", type=int, default=10, help="with --roi: full-frame scan every N frames")
    p.add_argument("--stable-frames", type=int, default=1)
    p.add_argument("--max-missing", type=int, default=3)
    p.add_argument("--font", default="Segoe UI")
    p.add_argument("--no-hide-unfocused", action="store_true", help="keep the overlay up when the game is not in front")
    p.add_argument("--capturable", action="store_true", help="do not exclude the overlay from screen capture")
    p.add_argument("--debug", action="store_true", help="outline every tracked block and print per-frame stats")
    p.add_argument("--dump-dir", help="debug: save every captured frame with OCR lines and blocks drawn")
    p.add_argument("--run-for", type=float, default=0.0, help="quit after N seconds (0 = run until the window closes)")
    p.add_argument("--screenshot", help="with --run-for: save a screenshot of the game area before quitting")
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
    from gametl.translate.dummy import EchoTranslator, UppercaseTranslator

    app = QApplication(sys.argv[:1])

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
        hwnd = info.hwnd
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

    engine = RapidOcrEngine(lang=args.lang)
    print(f"OCR warm-up {engine.warm_up(frame_w, frame_h):.0f}ms")
    translator = UppercaseTranslator() if args.translator == "uppercase" else EchoTranslator()

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
        target_lang=args.target_lang,
        debug=args.debug,
        dump_dir=args.dump_dir,
    )
    worker = PipelineThread(hwnd, engine, translator, config)
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
    if worker.ocr_ms:
        s = sorted(worker.ocr_ms)
        print(f"frames {worker.frames}, ocr median {s[len(s) // 2]:.0f}ms max {s[-1]:.0f}ms")
    return rc


if __name__ == "__main__":
    sys.exit(main())
