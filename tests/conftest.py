"""Fixtures shared by the tests. Each Qt test module picks its own platform
(offscreen, or the desktop the overlay tests need) before importing PySide6."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")  # physical pixels, as the app runs


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def keypair() -> tuple[bytes, str]:
    """A signing key made for the test: (private PEM, public key hex)."""
    from gametl.app.license import generate_keypair

    return generate_keypair()


@pytest.fixture(autouse=True)
def memory_registry(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """The trial's registry copy, kept in memory for every test: on Windows
    the real HKEY_CURRENT_USER value would otherwise leak between tests and
    use up the trial of whoever runs the suite."""
    from gametl.app import license

    values: dict[str, int] = {}
    monkeypatch.setattr(license, "_registry_get", lambda: values.get("trial"))
    monkeypatch.setattr(license, "_registry_set", lambda seconds: values.__setitem__("trial", int(seconds)))
    return values
