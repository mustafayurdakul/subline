"""Render the overlay onto a recorded video.

The same OCR, tracking, translation and subtitle painting as the live app,
applied frame by frame to a clip of game footage, written out as a GIF.
Made for the README demo; also a way to see what the app would do with a
game from a recording, without running the game.

  uv run python scripts/render_demo.py capture.mp4 --start 228 --end 237 --out docs/demo.gif

The default layout stacks the original frame above the translated one, so
a viewer sees both subtitles; `--layout single` shows only the result. The
translator comes from your settings (DeepL or Claude need their key,
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
from PIL import Image, ImageDraw, ImageFont
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

Box = tuple[int, int, int, int]
LABELS = {"original": "Game", "translated": "With gametl"}


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


def label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("segoeuib.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def panel(image_bgr: np.ndarray, crop: Box, size: tuple[int, int], label: str | None, font) -> Image.Image:
    """One output panel: the cropped, scaled frame with a corner label."""
    region = image_bgr[crop[1] : crop[3], crop[0] : crop[2]]
    small = cv2.resize(region, size, interpolation=cv2.INTER_AREA)
    out = Image.fromarray(small[:, :, ::-1])
    if label:
        draw = ImageDraw.Draw(out, "RGBA")
        text_w = draw.textlength(label, font=font)
        draw.rounded_rectangle((12, 12, 12 + text_w + 20, 12 + font.size + 14), radius=6, fill=(0, 0, 0, 170))
        draw.text((22, 18), label, font=font, fill=(255, 255, 255, 255))
    return out


def compose(
    original: np.ndarray, painted: np.ndarray, crop: Box, size: tuple[int, int], layout: str, font
) -> Image.Image:
    if layout == "single":
        return panel(painted, crop, size, None, font)
    top = panel(original, crop, size, LABELS["original"], font)
    bottom = panel(painted, crop, size, LABELS["translated"], font)
    divider = 4
    out = Image.new("RGB", (size[0], size[1] * 2 + divider), (24, 24, 24))
    out.paste(top, (0, 0))
    out.paste(bottom, (0, size[1] + divider))
    return out


def shared_palette(frames: list[Image.Image], colors: int) -> Image.Image:
    """One palette for the whole clip, from a mosaic of sampled frames: per-frame
    palettes make the GIF flicker as colours shift from frame to frame."""
    step = max(1, len(frames) // 12)
    sample = frames[::step][:12]
    w, h = sample[0].size
    mosaic = Image.new("RGB", (w, h * len(sample)))
    for index, frame in enumerate(sample):
        mosaic.paste(frame, (0, index * h))
    return mosaic.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--start", type=float, default=0.0, help="clip start, seconds")
    p.add_argument("--end", type=float, required=True, help="clip end, seconds")
    p.add_argument("--fps", type=float, default=10.0, help="frames per second in the output")
    p.add_argument("--roi", default="0.3,0.78,0.4,0.15", help="subtitle area as fractions of the frame")
    p.add_argument("--crop", default="0.15,0.5,0.7,0.5", help="part of the frame to keep in the output")
    p.add_argument("--width", type=int, default=900, help="output width in pixels")
    p.add_argument("--layout", choices=["stacked", "single"], default="stacked")
    p.add_argument("--font", type=int, default=56, help="subtitle font size in source pixels (0 = the game's own)")
    p.add_argument("--translator", default="deepl", choices=["deepl", "claude", "offline", "uppercase"])
    p.add_argument("--target-lang", default="tr")
    p.add_argument("--wait", type=float, default=5.0, help="seconds to wait for a translation per frame")
    p.add_argument("--colors", type=int, default=256, help="palette size shared by all GIF frames")
    p.add_argument("--no-dither", action="store_true", help="flat colours instead of dithering (smaller file)")
    p.add_argument("--out", default="docs/demo.gif")
    p.add_argument("--still", default="", help="also save the output frame at this time (seconds) as a PNG")
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
        max_missing=1,  # a short grace period: side by side, a lingering line would look wrong
    )
    translator = build_translator(settings, "demo", store, WindowsCredentialStore())
    service = TranslationService(translator, TranslationCache(), target_lang=args.target_lang, source_lang="en")
    engine = RapidOcrEngine(lang="en", model_root_dir=str(store.models_dir / "ocr"))
    config = OverlayController._pipeline_config(settings, (0, 0, width, height), None)
    pipeline = PipelineThread(0, engine, service, config)
    overlay = OverlayWindow(0)  # never shown: only its painter is used

    cx, cy, cw, ch = parse_fractions(args.crop)
    crop = (int(cx * width), int(cy * height), int((cx + cw) * width), int((cy + ch) * height))
    size = (args.width, int(args.width * (crop[3] - crop[1]) / (crop[2] - crop[0])))
    font = label_font(max(14, args.width // 40))

    frames: list[Image.Image] = []
    still: Image.Image | None = None
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
        composed = compose(image, painted, crop, size, args.layout, font)
        frames.append(composed)
        if args.still and still is None and t >= float(args.still):
            still = composed
        texts = [" / ".join(b.lines) for b in render]
        print(f"  {t:6.2f}s  {texts[0] if texts else '-'}", flush=True)
        t += 1.0 / args.fps
    service.shutdown()

    palette = shared_palette(frames, args.colors)
    dither = Image.Dither.NONE if args.no_dither else Image.Dither.FLOYDSTEINBERG
    quantized = [frame.quantize(palette=palette, dither=dither) for frame in frames]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        out,
        save_all=True,
        append_images=quantized[1:],
        duration=int(1000 / args.fps),
        loop=0,
        optimize=True,
    )
    print(f"wrote {out} ({out.stat().st_size / 1_000_000:.1f} MB, {len(frames)} frames, {quantized[0].size})")
    if still is not None:
        still.save(out.with_suffix(".png"))
        print(f"wrote {out.with_suffix('.png')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
