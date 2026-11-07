from __future__ import annotations

from gametl.layout.style import StyleMemory, ZoneStyle


def test_font_size_uses_the_band_median_once_enough_seen() -> None:
    mem = StyleMemory(band_px=64, min_samples=2)
    # First line in the subtitle band: only its own height counts.
    assert mem.font_px((300, 620, 900, 664), 1) == int(44 * 0.8)
    mem.observe((300, 620, 900, 664), 1, (0, 0, 0), (255, 255, 255), False)
    mem.observe((300, 622, 900, 660), 1, (0, 0, 0), (255, 255, 255), False)  # no descenders: shorter box
    mem.observe((300, 618, 900, 668), 1, (0, 0, 0), (255, 255, 255), False)  # taller box
    # A new short box in the same band gets the band's typical size, not its own.
    assert mem.font_px((300, 622, 900, 658), 1) == int(44 * 0.8)
    # Two-line blocks count per line and still land in the band.
    assert mem.font_px((300, 600, 900, 688), 2) == int(44 * 0.8)


def test_colors_and_busy_are_majorities() -> None:
    mem = StyleMemory(min_samples=2)
    box = (300, 620, 900, 664)
    assert mem.colors(box) is None
    assert mem.busy(box, default=True) is True
    mem.observe(box, 1, (10, 10, 10), (250, 250, 250), False)
    mem.observe(box, 1, (12, 11, 10), (255, 255, 250), False)
    mem.observe(box, 1, (90, 90, 90), (200, 200, 200), True)  # one odd sample
    assert mem.colors(box) == ((12, 11, 10), (250, 250, 250))
    assert mem.busy(box, default=True) is False


def test_zone_style_locks_after_a_few_lines_and_holds() -> None:
    zone = ZoneStyle(lock_after=3, window=6, drift=0.15)
    white = (255, 255, 255)
    assert zone.font_px(fallback=30) == 30 and zone.fg is None  # nothing seen: the caller's value
    zone.observe(40, white)
    assert zone.font_px(fallback=30) == 32 and not zone.locked  # running median while learning
    zone.observe(36, (250, 250, 250))
    zone.observe(44, white)
    assert zone.locked and zone.line_height == 40
    assert zone.font_px(fallback=30) == 32
    assert zone.fg == (255, 255, 255)  # the per-channel median of the three samples
    # A box with descenders, a two-line block measured per line, a short word: all render at 32 px.
    for height in (46, 38, 30, 50, 41):
        zone.observe(height, white)
        assert zone.font_px(fallback=30) == 32


def test_zone_style_follows_a_real_size_change_only_over_a_full_window() -> None:
    zone = ZoneStyle(lock_after=2, window=4, drift=0.15)
    for _ in range(2):
        zone.observe(40, (255, 255, 255))
    assert zone.line_height == 40
    zone.observe(60, (255, 255, 255))  # one odd reading: ignored
    assert zone.line_height == 40
    for _ in range(3):
        zone.observe(60, (255, 255, 255))  # the game really changed its size: the window is all 60 now
    assert zone.line_height == 60


def test_other_bands_do_not_mix() -> None:
    mem = StyleMemory(band_px=64, min_samples=2)
    for _ in range(3):
        mem.observe((20, 40, 240, 70), 1, (0, 0, 0), (255, 255, 255), False)  # HUD, 30 px lines
    assert mem.font_px((300, 620, 900, 664), 1) == int(44 * 0.8)  # subtitle band unaffected
