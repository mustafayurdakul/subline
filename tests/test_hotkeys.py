from __future__ import annotations

import pytest

from gametl.app.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, GlobalHotkeys, parse_combo


def test_parse_combo_letters_function_and_named_keys() -> None:
    assert parse_combo("ctrl+shift+t") == (MOD_CONTROL | MOD_SHIFT, ord("T"))
    assert parse_combo("Alt + F5") == (MOD_ALT, 0x74)
    assert parse_combo("ctrl+space") == (MOD_CONTROL, 0x20)
    assert parse_combo("f12") == (0, 0x7B)


@pytest.mark.parametrize("bad", ["", "ctrl+", "ctrl+shift", "meta+x", "ctrl+hyper", "ctrl+f99", "ctrl+ş", "alt+٣"])
def test_parse_combo_rejects_nonsense(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_combo(bad)


def test_register_and_unregister_round_trip() -> None:
    hotkeys = GlobalHotkeys()
    fired = []
    # An obscure combination unlikely to be taken on the test machine.
    assert hotkeys.register("test", "ctrl+alt+shift+f11", lambda: fired.append(1)) is True
    assert hotkeys.registered == ["test"]
    assert hotkeys.register("bad", "nope+", lambda: None) is False
    hotkeys.unregister_all()
    assert hotkeys.registered == []


def test_registering_replaces_the_binding_and_a_bad_one_leaves_it_unbound() -> None:
    hotkeys = GlobalHotkeys()
    try:
        assert hotkeys.register("test", "ctrl+alt+shift+f11", lambda: None) is True
        assert hotkeys.register("test", "ctrl+alt+shift+f11", lambda: None) is True  # same keys again: fine
        assert hotkeys.register("test", "ctrl+alt+shift+f12", lambda: None) is True  # moved
        assert hotkeys.registered == ["test"]
        assert hotkeys.register("test", "ctrl+hyper", lambda: None) is False  # typo
        assert hotkeys.registered == []  # what the call says is what holds: nothing
    finally:
        hotkeys.unregister_all()
