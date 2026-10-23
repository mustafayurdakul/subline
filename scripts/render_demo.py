"""Render the overlay onto a recorded video.

The same OCR, tracking, translation and subtitle painting as the live app,
applied frame by frame to a clip of game footage, written out as a GIF and
a still image. Made for the README demo; also a way to see what the app
would do with a game from a recording, without running the game.

  uv run python scripts/render_demo.py capture.mp4 --start 508 --end 520 --out docs/demo.gif

The translator comes from your settings (DeepL or Claude need their key,
`--translator uppercase` needs nothing). `--roi` is the subtitle area as
fractions of the frame, like the app's area selection.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

import cv2
import numpy as np
from PIL import Image
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from gametl.app.config import ProfileStore, Settings
from gametl.app.controller import OverlayController, build_translator
from gametl.app.credentials import WindowsCredentialStore
from gametl.app.main import utf8_console
from gametl.app.pipeline import PipelineThread
from gametl.capture.base import Frame
from gametl.ocr.rapid import RapidOcrEngine
from gametl.overlay.window import OverlayWindow
from gametl.translate.cache import TranslationCache
from gametl.translate.service import TranslationService


def parse_fractions(spec: str) -> tuple[float, float, float, float]:
    x, y, w, h = (float(v) for v in spec.split(","))
    return x, y, w, h


def paint_onto(image_bgr: np.ndarray, overlay: OverlayWindow, blocks) -> np.ndarray:
    """Draw the overlay's blocks onto a copy of a BGR frame."""
    rgb = np.ascontiguousarray(image_bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    qimage = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    painter = QPainter(qimage)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    try:
        overlay.paint_blocks(painter, blocks)
    finally:
        painter.end()
    out = np.frombuffer(qimage.constBits(), dtype=np.uint8).reshape(h, qimage.bytesPerLine())[:, : 3 * w]
    return np.ascontiguousarray(out.reshape(h, w, 3)[:, :, ::-1])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--start", type=float, default=0.0, help="clip start, seconds")
    p.add_argument("--end", type=float, required=True, help="clip end, seconds")
    p.add_argument("--fps", type=float, default=10.0, help="frames per second in the output")
    p.add_argument("--roi", default="0.25,0.74,0.5,0.2", help="subtitle area as fractions of the frame")
    p.add_argument("--crop", default="0.15,0.45,0.7,0.55", help="part of the frame to keep in the output")
    p.add_argument("--width", type=int, default=896, help="output width in pixels")
    p.add_argument("--font", type=int, default=0, help="subtitle font size in source pixels (0 = the game's own)")
    p.add_argument("--translator", default="deepl", choices=["deepl", "claude", "offline", "uppercase"])
    p.add_argument("--target-lang", default="tr")
    p.add_argument("--wait", type=float, default=5.0, help="seconds to wait for a translation per frame")
    p.add_argument("--colors", type=int, default=96, help="palette size per GIF frame (fewer = smaller file)")
    p.add_argument("--out", default="docs/demo.gif")
    p.add_argument("--still", default="", help="also save this frame (seconds) as a PNG next to the GIF")
    p.add_argument("--data-dir", help="app data dir (default %%APPDATA%%\\gametl)")
    args = p.parse_args()
    utf8_console()  # translations are printed as they arrive

    app = QApplication.instance() or QApplication([])  # noqa: F841 (fonts need a GUI application)
    capture = cv2.VideoCapture(args.video)
    if not capture.isOpened():
        print(f"cannot open {args.video}")
        return 2
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0

    # The app's own building blocks, configured as a profile would be.
    store = ProfileStore(args.data_dir)
    settings = Settings(
        translator=args.translator,
        target_lang=args.target_lang,
        roi=args.roi,
        subtitle_font_px=args.font,
        use_cache_file=False,
    )
    translator = build_translator(settings, "demo", store, WindowsCredentialStore())
    service = TranslationService(translator, TranslationCache(), target_lang=args.target_lang, source_lang="en")
    engine = RapidOcrEngine(lang="en", model_root_dir=str(store.models_dir / "ocr"))
    config = OverlayController._pipeline_config(settings, (0, 0, width, height), None)
    pipeline = PipelineThread(0, engine, service, config)
    overlay = OverlayWindow(0)  # never shown: only its painter is used

    cx, cy, cw, ch = parse_fractions(args.crop)
    crop = (int(cx * width), int(cy * height), int((cx + cw) * width), int((cy + ch) * height))
    out_size = (args.width, int(args.width * (crop[3] - crop[1]) / (crop[2] - crop[0])))

    frames: list[Image.Image] = []
    still: np.ndarray | None = None
    t = args.start
    print(f"{args.video}: {width}x{height}, rendering {args.start:.1f}-{args.end:.1f}s at {args.fps:g} fps")
    while t < args.end:
        capture.set(cv2.CAP_PROP_POS_FRAMES, round(t * source_fps))
        ok, image = capture.read()
        if not ok:
            break
        frame = Frame(image=image, timestamp=t)
        blocks, _ = pipeline.track_frame(frame)
        pipeline.render_blocks(blocks, frame)  # queues translations for new text
        deadline = time.monotonic() + args.wait
        while service.pending and time.monotonic() < deadline:  # offline, so waiting is fine
            service.drain()
            time.sleep(0.02)
        render = pipeline.render_blocks(blocks, frame)
        painted = paint_onto(image, overlay, render)
        if args.still and still is None and t >= float(args.still):
            still = painted
        region = painted[crop[1] : crop[3], crop[0] : crop[2]]
        small = cv2.resize(region, out_size, interpolation=cv2.INTER_AREA)
        frame_rgb = Image.fromarray(small[:, :, ::-1])
        frames.append(frame_rgb.quantize(colors=args.colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
        texts = [" / ".join(b.lines) for b in render]
        print(f"  {t:6.2f}s  {texts[0] if texts else '-'}", flush=True)
        t += 1.0 / args.fps
    service.shutdown()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / args.fps),
        loop=0,
        optimize=False,
    )
    print(f"wrote {out} ({out.stat().st_size / 1_000_000:.1f} MB, {len(frames)} frames)")
    if still is not None:
        still_path = out.with_suffix(".png")
        region = still[crop[1] : crop[3], crop[0] : crop[2]]
        cv2.imwrite(str(still_path), cv2.resize(region, (1280, int(1280 * region.shape[0] / region.shape[1]))))
        print(f"wrote {still_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
