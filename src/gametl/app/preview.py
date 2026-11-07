"""The Appearance page's live preview: the subtitle as the overlay would
draw it, painted by the same BlockPainter from the settings in the window,
handed to QML as an image (`image://overlay/...`).

The image is the area read in a game frame that stands for a 1080p game,
so pixel sizes are scaled by the image's width over 1920: a 40 px subtitle
looks as large against the frame as it would in the game. The game's own
line is drawn too, so the pill, the position and "Hide the original line"
show what they do to it."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider

from ..overlay.paint import BlockPainter, RenderBlock
from .config import Settings
from .controller import parse_color
from .settings_backend import SettingsBackend

PROVIDER = "overlay"  # the image:// scheme's host
TRANSLATED_LINE = "Nereye gidiyorsun? Işıklar söndüğünde buradaydın."
SOURCE_LINE = "Where are you going? You were here when the lights went out."
SOURCE_COLOR = (226, 226, 226)  # the game's own subtitle: a light grey with a shadow, as many games draw it
REFERENCE_WIDTH = 1920  # the game the preview frame stands for: 1080p
DEFAULT_FONT_PX = 36  # at 1080p, when the size is the game's own, which the preview cannot know
DEFAULT_COLOR = (242, 242, 242)


def preview_blocks(settings: Settings, width: int, height: int, painter: BlockPainter) -> list[RenderBlock]:
    """The game's line and its translation over it, in an area of `width`
    x `height` with the settings' look. The game's line sits in the middle
    of the area; `painter` measures it, so the band that hides it fits."""
    scale = width / REFERENCE_WIDTH
    font_px = max(6, min(round((settings.subtitle_font_px or DEFAULT_FONT_PX) * scale), height))
    metrics = painter.metrics_at(font_px)
    half_w = min(width - 4, metrics.horizontalAdvance(SOURCE_LINE)) // 2
    half_h = metrics.height() // 2
    cx, cy = width // 2, height // 2
    bbox = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    zone = (0, 0, width, height)
    source = RenderBlock(
        bbox=bbox,
        lines=[SOURCE_LINE],
        fg=SOURCE_COLOR,
        style="subtitle",
        font_px=font_px,
        zone=zone,
        position="source",
        background="shadow",
        hide_source=False,
    )
    translation = RenderBlock(
        bbox=bbox,
        lines=[TRANSLATED_LINE],
        fg=parse_color(settings.subtitle_color) if settings.subtitle_color.strip() else DEFAULT_COLOR,
        style="subtitle",
        font_px=font_px,
        zone=zone,
        position=settings.subtitle_position,
        background=settings.subtitle_background,
        pill_alpha=settings.subtitle_pill_alpha,  # the painter clamps it
        weight=settings.subtitle_weight,
        hide_source=settings.subtitle_hide_source,
    )
    return [source, translation]


def render_preview(settings: Settings, width: int, height: int) -> QImage:
    """A transparent image of the area with the game's line and the subtitle on it."""
    image = QImage(QSize(width, height), QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    try:
        block_painter = BlockPainter(settings.font)
        game_line, translation = preview_blocks(settings, width, height, block_painter)
        # Two calls: within one, every text goes on after every background, and the
        # game's line must lie under the translation's band, as it does in the game.
        block_painter.paint_blocks(painter, [game_line])
        block_painter.paint_blocks(painter, [translation])
    finally:
        painter.end()
    return image


class PreviewImageProvider(QQuickImageProvider):
    """Answers `image://overlay/<anything>` with the current settings'
    subtitle at the size the Image asks for; the page changes the id to
    ask again."""

    def __init__(self, backend: SettingsBackend) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.backend = backend

    def requestImage(self, _id: str, size: QSize, requested: QSize) -> QImage:
        width = requested.width() if requested.width() > 0 else 680
        height = requested.height() if requested.height() > 0 else 170
        image = render_preview(self.backend.to_settings(), width, height)
        size.setWidth(width)
        size.setHeight(height)
        return image
