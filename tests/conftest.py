"""Shared pytest fixtures and network guard."""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

import httpx
import pytest


class RealNetworkBlockedError(RuntimeError):
    """Raised when a test attempts to construct a real HTTP transport or make network calls."""


@pytest.fixture(autouse=True)
def block_real_http_client(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail any non-live test that constructs a real HTTP client instead of MockTransport."""
    if request.node.get_closest_marker("live") is not None:
        return

    def _forbid_transport(*args: object, **kwargs: object) -> None:
        raise RealNetworkBlockedError(
            "Constructing a real HTTP client/transport is forbidden in tests. "
            "Pass httpx.MockTransport instead, or mark the test with @pytest.mark.live."
        )

    monkeypatch.setattr(httpx.HTTPTransport, "__init__", _forbid_transport)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "__init__", _forbid_transport)
    monkeypatch.setattr(urllib.request, "urlopen", _forbid_transport)


@pytest.fixture
def repo_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run a test inside a throwaway copy of the repo inputs so tracked artifacts stay untouched."""
    for rel in ["config", "queries", "data", "artifacts", "reports"]:
        shutil.copytree(rel, tmp_path / rel)
    monkeypatch.chdir(tmp_path)
    return tmp_path
