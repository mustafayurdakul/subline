"""Key storage and lookup. The Windows test writes one throwaway entry under
a test prefix into the real Credential Manager and deletes it again."""

from __future__ import annotations

import pytest

from gametl.app.credentials import (
    MemorySecretStore,
    WindowsCredentialStore,
    has_anthropic_credentials,
    key_status,
    resolve_key,
)


def test_windows_store_round_trip() -> None:
    store = WindowsCredentialStore(prefix="gametl-test")
    store.delete("ROUND_TRIP")
    assert store.get("ROUND_TRIP") is None
    try:
        store.set("ROUND_TRIP", "abc:fx-ğüş")  # non-ASCII survives the UTF-16 blob
        assert store.get("ROUND_TRIP") == "abc:fx-ğüş"
        store.set("ROUND_TRIP", "second")  # overwrite
        assert store.get("ROUND_TRIP") == "second"
    finally:
        store.delete("ROUND_TRIP")
    assert store.get("ROUND_TRIP") is None
    store.delete("ROUND_TRIP")  # deleting a missing entry is not an error


def test_store_wins_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = MemorySecretStore()
    monkeypatch.delenv("TEST_GAMETL_KEY", raising=False)
    assert resolve_key("TEST_GAMETL_KEY", secrets) is None
    assert key_status("TEST_GAMETL_KEY", secrets) == "not set"

    monkeypatch.setenv("TEST_GAMETL_KEY", "from-env")
    assert resolve_key("TEST_GAMETL_KEY", secrets) == ("from-env", "environment variable")
    secrets.set("TEST_GAMETL_KEY", "from-store")
    assert resolve_key("TEST_GAMETL_KEY", secrets) == ("from-store", "memory")
    assert key_status("TEST_GAMETL_KEY", secrets) == "set (memory)"


def test_anthropic_credentials_from_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr("gametl.app.credentials.user_environment_variable", lambda name: None)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    secrets = MemorySecretStore()
    assert has_anthropic_credentials(secrets) is False
    secrets.set("ANTHROPIC_API_KEY", "sk-test")
    assert has_anthropic_credentials(secrets) is True
