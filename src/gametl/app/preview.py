"""The Appearance page's live preview: the subtitle as the overlay would
draw it, painted by the same BlockPainter from the settings in the window,
handed to QML as an image (`image://overlay/...`).

The image is the area read in a game frame that stands for a 1080p game,
so pixel sizes are scaled by the image's width over 1920: a 40 px subtitle
looks as large against the frame as it would in the game. The game's own
line is drawn too, so the pill, the position and "Hide the original line"
show what they do to it. In chat mode the image is the whole frame, with
the game's line in the bottom strip and the chat card above it."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider

from ..overlay.paint import CHAT_CORNERS, BlockPainter, ChatCard, ChatLine, Drawable, RenderBlock
from .config import Settings, chat_width_share
from .controller import parse_color
from .settings_backend import SettingsBackend

PROVIDER = "overlay"  # the image:// scheme's host
LINE = "Nereye gidiyorsun? Işıklar söndüğünde buradaydın."
SOURCE_LINE = "Where are you going? You were here when the lights went out."
SOURCE_COLOR = (226, 226, 226)  # the game's own subtitle: a light grey with a shadow, as many games draw it
REFERENCE_WIDTH = 1920  # the game the preview frame stands for: 1080p
DEFAULT_FONT_PX = 36  # at 1080p, when the size is the game's own, which the preview cannot know
DEFAULT_COLOR = (242, 242, 242)
STRIP = 0.25  # of the frame: the bottom strip the game's line sits in, as the default area
# The chat card's sample: what was said before the game's line, and the line itself last, with the times.
CHAT_LINES = [
    ("21:36:05", "Casey", "Nereye gidiyorsun?"),
    ("21:36:11", "Alan", "Işıklar söndüğünde buradaydın."),
    ("21:36:18", "Casey", "Sanki sinyal kalitesi kötüymüş gibi geliyor."),
]


def chat_preview(settings: Settings) -> bool:
    """Whether the preview shows chat mode: the whole frame, not the strip alone."""
    return settings.render == "chat"


def preview_blocks(settings: Settings, width: int, height: int, painter: BlockPainter) -> list[Drawable]:
    """The game's line and its translation over it, in an area of `width`
    x `height` with the settings' look. The game's line sits in the middle
    of the area; `painter` measures it, so the band that hides it fits. In
    chat mode the area is the whole frame, the game's line sits in its
    bottom strip and the chat card above it, with the line as its newest
    entry."""
    scale = width / REFERENCE_WIDTH
    chat = chat_preview(settings)
    strip_h = round(height * STRIP) if chat else height
    font_px = max(6, min(round((settings.subtitle_font_px or DEFAULT_FONT_PX) * scale), strip_h))
    metrics = painter.metrics_at(font_px)
    half_w = min(width - 4, metrics.horizontalAdvance(SOURCE_LINE)) // 2
    half_h = metrics.height() // 2
    cx, cy = width // 2, height - strip_h // 2
    bbox = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    zone = (0, height - strip_h, width, height)
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
    colour = parse_color(settings.subtitle_color) if settings.subtitle_color.strip() else None
    pill_alpha = max(0, min(255, int(settings.subtitle_pill_alpha)))
    if chat:
        shown = CHAT_LINES[-max(1, int(settings.chat_lines)) :]
        speakers = {name: i for i, name in enumerate(dict.fromkeys(name for _, name, _ in CHAT_LINES))}
        stamps = bool(settings.chat_timestamps)
        card = ChatCard(
            area=(0, 0, width, height),
            lines=[ChatLine(name, text, speakers[name], stamp if stamps else "") for stamp, name, text in shown],
            zone=zone,
            corner=settings.chat_corner if settings.chat_corner in CHAT_CORNERS else CHAT_CORNERS[0],
            width=chat_width_share(settings.chat_width),
            font_px=font_px,
            fg=colour or (255, 255, 255),
            weight=settings.subtitle_weight,
            alpha=pill_alpha,
            covers=[bbox] if settings.subtitle_hide_source else [],
        )
        return [source, card]
    translation = RenderBlock(
        bbox=bbox,
        lines=[LINE],
        fg=colour or DEFAULT_COLOR,
        style="subtitle",
        font_px=font_px,
        zone=zone,
        position=settings.subtitle_position,
        background=settings.subtitle_background,
        pill_alpha=pill_alpha,
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
        blocks = BlockPainter(settings.font)
        game_line, translation = preview_blocks(settings, width, height, blocks)
        # Two calls: within one, every text goes on after every background, and the
        # game's line must lie under the translation's band, as it does in the game.
        blocks.paint_blocks(painter, [game_line])
        blocks.paint_blocks(painter, [translation])
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
        settings = self.backend.to_settings()
        width = requested.width() if requested.width() > 0 else 680
        height = requested.height()
        if height <= 0:
            height = round(width * 9 / 16) if chat_preview(settings) else 170
        image = render_preview(settings, width, height)
        size.setWidth(width)
        size.setHeight(height)
        return image
