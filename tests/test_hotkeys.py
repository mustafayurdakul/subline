"""Registering real hotkeys with Windows. RegisterHotKey needs an
interactive desktop session, which CI's hosted runners do not have, so CI
leaves this module out; run it on a Windows desktop. The parsing and
message tests are in test_hotkeys_headless.py."""

from __future__ import annotations

from gametl.app.hotkeys import GlobalHotkeys


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
