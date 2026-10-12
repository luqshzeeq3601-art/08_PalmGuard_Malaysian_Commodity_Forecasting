"""Contract tests for PalmGuard container environment and packaging (Task T21)."""

from __future__ import annotations

from pathlib import Path


def test_dockerfile_structure():
    """Verify Dockerfile contains required production directives and libgomp1."""
    df_path = Path("Dockerfile")
    assert df_path.exists()
    content = df_path.read_text(encoding="utf-8")
    assert "FROM python:3.11-slim" in content
    assert "libgomp1" in content
    assert "HEALTHCHECK" in content
    assert "uvicorn" in content


def test_dockerignore_structure():
    """Verify .dockerignore excludes heavy or sensitive paths."""
    di_path = Path(".dockerignore")
    assert di_path.exists()
    content = di_path.read_text(encoding="utf-8")
    assert ".venv" in content
    assert ".git" in content
    assert "data/raw/" in content
