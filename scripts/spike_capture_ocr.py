"""Diagnostic tool: capture a window with Windows Graphics Capture, OCR every
frame, print text, boxes and per-stage timings, and save the last annotated
frame. Useful for checking what OCR sees before involving the overlay.

Examples:
  python scripts/spike_capture_ocr.py --list-windows
  python scripts/spike_capture_ocr.py --window "Notepad" --seconds 5
  python scripts/spike_capture_ocr.py --window "Game" --roi 0,0.7,1,0.3 --lang en
  python scripts/spike_capture_ocr.py --image screenshot.png --lang japan
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from gametl.app.controller import parse_zone
from gametl.capture.base import Frame
from gametl.capture.windows import (
    client_rect_on_screen,
    enable_per_monitor_dpi_awareness,
    find_window,
    list_windows,
    window_rect,
)
from gametl.ocr.base import OcrResult
from gametl.ocr.rapid import RapidOcrEngine


def frame_diff(previous: np.ndarray | None, image: np.ndarray) -> tuple[float, np.ndarray]:
    """Mean absolute difference (0..255) between `image` and the previous
    thumbnail, on a 1/8-scale grey thumbnail; returns (diff, new thumbnail)."""
    thumb = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None, fx=0.125, fy=0.125)
    if previous is None or previous.shape != thumb.shape:
        return 255.0, thumb
    return float(np.mean(cv2.absdiff(previous, thumb))), thumb


def annotate(image: np.ndarray, result: OcrResult) -> np.ndarray:
    out = image.copy()
    for i, line in enumerate(result.lines):
        pts = line.quad.astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(out, [pts], True, (0, 255, 0), 2)
        x0, y0, _, _ = line.bbox
        cv2.putText(out, str(i), (x0, max(12, y0 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    return out


def print_lines(result: OcrResult, indent: str = "  ") -> None:
    for i, line in enumerate(result.lines):
        x0, y0, x1, y1 = line.bbox
        print(f"{indent}{i:2d} [{line.confidence:.2f}] ({x0},{y0})-({x1},{y1}) {line.text}")


def fmt_timings(t: dict[str, float]) -> str:
    return " ".join(f"{k}={v:.0f}ms" for k, v in t.items())


def make_engine(args: argparse.Namespace) -> RapidOcrEngine:
    t0 = time.perf_counter()
    engine = RapidOcrEngine(
        lang=args.lang,
        version=args.version,
        size=args.size,
        use_dml=args.dml,
        det_limit_side_len=args.det_limit,
    )
    warm_ms = engine.warm_up()
    print(
        f"OCR engine: {args.version} {args.size} lang={args.lang} dml={args.dml} "
        f"init={(time.perf_counter() - t0) * 1000:.0f}ms (warm-up {warm_ms:.0f}ms)"
    )
    return engine


def run_image(args: argparse.Namespace) -> int:
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        print(f"cannot read image: {args.image}")
        return 2
    engine = make_engine(args)
    h, w = image.shape[:2]
    x0, y0, x1, y1 = parse_zone(args.roi, w, h) or (0, 0, w, h)
    crop = image[y0:y1, x0:x1]
    print(f"image {w}x{h}, roi ({x0},{y0})-({x1},{y1})")

    result = None
    totals = []
    for _ in range(args.repeat):
        result = engine.recognize(crop).shifted(x0, y0)
        totals.append(result.timings_ms["total"])
        print(f"  {fmt_timings(result.timings_ms)}")
    assert result is not None
    print(f"{len(result.lines)} lines; median total {statistics.median(totals):.0f}ms over {args.repeat} runs")
    print_lines(result)
    save_outputs(args.save, image, result, stem=Path(args.image).stem)
    return 0


def run_window(args: argparse.Namespace) -> int:
    from gametl.capture.wgc import WgcWindowCapture

    if args.hwnd:
        hwnd = int(args.hwnd, 0)
        title = "(by hwnd)"
    else:
        deadline = time.perf_counter() + args.wait
        info = find_window(args.window)
        while info is None and time.perf_counter() < deadline:
            time.sleep(0.5)
            info = find_window(args.window)
        if info is None:
            print(f"no visible window with title containing {args.window!r}; try --list-windows")
            return 2
        hwnd, title = info.hwnd, info.title

    dwm = window_rect(hwnd)
    client = client_rect_on_screen(hwnd)
    print(f"window: {title!r} hwnd=0x{hwnd:X}")
    print(f"  dwm bounds  {dwm}  size {dwm[2] - dwm[0]}x{dwm[3] - dwm[1]}")
    print(f"  client rect {client}  size {client[2] - client[0]}x{client[3] - client[1]}")

    engine = make_engine(args)

    interval_ms = int(1000 / args.fps_cap) if args.fps_cap else None
    ocr_totals: list[float] = []
    det_times: list[float] = []
    rec_times: list[float] = []
    capture_gaps: list[float] = []
    skipped = 0
    last_thumb = None
    last_frame: Frame | None = None
    last_result: OcrResult | None = None
    last_ts = None
    roi = None

    print(f"capturing for {args.seconds:.0f}s ...")
    t_start = time.perf_counter()
    with WgcWindowCapture(hwnd, min_interval_ms=interval_ms) as cap:
        while time.perf_counter() - t_start < args.seconds:
            frame = cap.next_frame(timeout=2.0)
            if frame is None:
                if cap.closed:
                    print("capture closed (window gone)")
                    break
                print("  (no frame within 2s; is the window visible and not minimized?)")
                continue
            if last_ts is not None:
                capture_gaps.append((frame.timestamp - last_ts) * 1000)
            last_ts = frame.timestamp

            if roi is None:
                roi = parse_zone(args.roi, frame.width, frame.height) or (0, 0, frame.width, frame.height)
                print(
                    f"  first frame {frame.width}x{frame.height} "
                    f"(dwm {dwm[2] - dwm[0]}x{dwm[3] - dwm[1]}, "
                    f"client {client[2] - client[0]}x{client[3] - client[1]}); roi {roi}"
                )
            x0, y0, x1, y1 = roi
            crop = frame.image[y0:y1, x0:x1]

            diff, thumb = frame_diff(last_thumb, crop)
            last_thumb = thumb
            if not args.always_ocr and diff < args.diff_threshold and last_result is not None:
                skipped += 1
                continue

            result = engine.recognize(crop).shifted(x0, y0)
            ocr_totals.append(result.timings_ms["total"])
            if "det" in result.timings_ms:
                det_times.append(result.timings_ms["det"])
            if "rec" in result.timings_ms:
                rec_times.append(result.timings_ms["rec"])
            last_frame, last_result = frame, result

            print(
                f"t=+{time.perf_counter() - t_start:5.2f}s diff={diff:5.1f} "
                f"{fmt_timings(result.timings_ms)} lines={len(result.lines)}"
            )
            if not args.quiet:
                print_lines(result)

    print()
    print(f"frames received: {cap.frames_received}, OCR runs: {len(ocr_totals)}, skipped (unchanged): {skipped}")
    if capture_gaps:
        print(
            f"capture interval: median {statistics.median(capture_gaps):.0f}ms "
            f"(~{1000 / statistics.median(capture_gaps):.1f} fps)"
        )
    for name, series in (("ocr total", ocr_totals), ("det", det_times), ("rec", rec_times)):
        if series:
            s = sorted(series)
            p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
            print(
                f"{name:9s}: median {statistics.median(s):.0f}ms  p95 {p95:.0f}ms  min {s[0]:.0f}ms  max {s[-1]:.0f}ms"
            )

    if last_frame is not None and last_result is not None:
        save_outputs(args.save, last_frame.image, last_result, stem="capture")
    return 0


def save_outputs(save_dir: str | None, image: np.ndarray, result: OcrResult, stem: str) -> None:
    if not save_dir:
        return
    out = Path(save_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw = out / f"{stem}_raw.png"
    ann = out / f"{stem}_annotated.png"
    cv2.imwrite(str(raw), image)
    cv2.imwrite(str(ann), annotate(image, result))
    print(f"saved {raw} and {ann}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--list-windows", action="store_true", help="list capturable windows and exit")
    src.add_argument("--window", help="title substring of the window to capture")
    src.add_argument("--hwnd", help="window handle (decimal or 0x hex)")
    src.add_argument("--image", help="run OCR on an image file instead of a live window")
    p.add_argument("--seconds", type=float, default=5.0, help="capture duration")
    p.add_argument("--wait", type=float, default=0.0, help="seconds to wait for the window to appear")
    p.add_argument("--fps-cap", type=float, default=10.0, help="max capture rate (0 = uncapped)")
    p.add_argument("--roi", help="x,y,w,h as fractions (0-1) or pixels; default whole frame")
    p.add_argument("--lang", default="en", help="OCR language code (en, ch, japan, korean, de, fr, ...)")
    p.add_argument("--version", default="PP-OCRv6", help="PP-OCRv4 | PP-OCRv5 | PP-OCRv6")
    p.add_argument("--size", default="small", help="tiny | small | medium (v6) or mobile | server (v4/v5)")
    p.add_argument("--det-limit", type=int, default=960, help="cap on the long side fed to the detector")
    p.add_argument("--dml", action="store_true", help="use DirectML GPU (needs onnxruntime-directml)")
    p.add_argument("--diff-threshold", type=float, default=1.0, help="skip OCR when frame diff is below this")
    p.add_argument("--always-ocr", action="store_true", help="OCR every frame, no diff skipping")
    p.add_argument("--repeat", type=int, default=3, help="OCR runs for --image timing")
    p.add_argument("--save", default="out", help="directory for raw + annotated frames ('' to disable)")
    p.add_argument("--quiet", action="store_true", help="only print per-frame summaries")
    args = p.parse_args(argv)

    enable_per_monitor_dpi_awareness()

    if args.list_windows:
        for w in sorted(list_windows(), key=lambda w: w.title.casefold()):
            print(f"0x{w.hwnd:08X} {w.width:5d}x{w.height:<5d} [{w.class_name}] {w.title}")
        return 0
    if args.image:
        return run_image(args)
    if args.window or args.hwnd:
        return run_window(args)
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
