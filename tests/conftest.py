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
