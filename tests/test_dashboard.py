"""Tests for the PalmGuard Streamlit dashboard (Task T22)."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_renders_without_exception():
    """Verify Streamlit app initializes, reads published artifacts, and renders tabs."""
    app_path = Path("dashboard/app.py").resolve()
    assert app_path.exists()

    at = AppTest.from_file(str(app_path), default_timeout=30)
    at.run()

    # Confirm title and warning disclaimers exist
    assert not at.exception
    assert len(at.title) >= 1
    assert "PalmGuard" in at.title[0].value
    assert len(at.warning) >= 1
    assert "Notice & Disclaimer" in at.warning[0].value
    assert len(at.tabs) >= 1
