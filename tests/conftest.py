"""Fixtures shared by the tests. Each Qt test module sets the offscreen
platform before importing PySide6. One process has one Qt platform, so
test_overlay_window.py, which needs the Windows desktop, skips in a full
run and runs only on its own."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")  # physical pixels, as the app runs


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_user_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Key lookups read this process's environment only. The Windows user
    environment in the registry can hold the developer's real API keys,
    which no test may find, send or print."""
    monkeypatch.setattr("gametl.app.credentials.user_environment_variable", lambda name: os.environ.get(name) or None)
