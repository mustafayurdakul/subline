"""The Appearance page's live preview: the subtitle as the overlay would
draw it, painted by the same BlockPainter from the settings in the window,
handed to QML as an image (`image://overlay/...`)."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider

from ..overlay.paint import BlockPainter, RenderBlock
from .config import Settings
from .controller import parse_color
from .settings_backend import SettingsBackend

PROVIDER = "overlay"  # the image:// scheme's host
LINE = "Nereye gidiyorsun? Işıklar söndüğünde buradaydın."
DEFAULT_FONT_PX = 22  # when the size is the game's own, which the preview cannot know
DEFAULT_COLOR = (242, 242, 242)


def preview_block(settings: Settings, width: int, height: int) -> RenderBlock:
    """The sample line laid out in a zone of `width` x `height` with the
    settings' look. The source line is imagined a third of the way up."""
    font_px = settings.subtitle_font_px or DEFAULT_FONT_PX
    font_px = max(8, min(font_px, height // 3))
    source_y = height * 2 // 3
    return RenderBlock(
        bbox=(width // 4, source_y - font_px // 2, width * 3 // 4, source_y + font_px // 2),
        lines=[LINE],
        fg=parse_color(settings.subtitle_color) if settings.subtitle_color.strip() else DEFAULT_COLOR,
        style="subtitle",
        font_px=font_px,
        zone=(0, 0, width, height),
        position=settings.subtitle_position,
        background=settings.subtitle_background,
        pill_alpha=max(0, min(255, int(settings.subtitle_pill_alpha))),
        weight=settings.subtitle_weight,
        grain=max(0, min(100, int(settings.subtitle_grain))),
        hide_source=False,
    )


def render_preview(settings: Settings, width: int, height: int) -> QImage:
    """A transparent image of the preview zone with the subtitle on it."""
    image = QImage(QSize(width, height), QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    try:
        BlockPainter(settings.font).paint_blocks(painter, [preview_block(settings, width, height)])
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
        height = requested.height() if requested.height() > 0 else 382
        image = render_preview(self.backend.to_settings(), width, height)
        size.setWidth(width)
        size.setHeight(height)
        return image
