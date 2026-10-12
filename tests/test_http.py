"""Tests for the polite HTTP client, backoff retry and per-host throttling (Task T02)."""

from __future__ import annotations

import httpx
import pytest
from conftest import RealNetworkBlockedError

from palmguard.http import (
    DEFAULT_HOST_INTERVALS,
    DEFAULT_USER_AGENT,
    PoliteTransport,
    create_http_client,
    fetch_url,
)


class FakeClock:
    """Deterministic monotonic clock and sleep recorder for throttle/backoff tests."""

    def __init__(self, initial: float = 100.0) -> None:
        self.now = initial
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_real_http_client_raises_in_tests() -> None:
    """Confirm the autouse conftest fixture blocks constructing real HTTP clients."""
    with pytest.raises(RealNetworkBlockedError):
        httpx.Client()

    with pytest.raises(RealNetworkBlockedError):
        create_http_client()


def test_user_agent_and_fetch_url() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(dict(request.headers))
        return httpx.Response(
            200, content=b'{"ok": true}', headers={"Content-Type": "application/json"}
        )

    with create_http_client(transport=httpx.MockTransport(handler)) as client:
        res = fetch_url(client, "https://www.worldbank.org/en/research/commodity-markets")

    assert seen_headers.get("user-agent") == DEFAULT_USER_AGENT
    assert res.http_status == 200
    assert res.content == b'{"ok": true}'
    assert res.request_url == "https://www.worldbank.org/en/research/commodity-markets"
    assert res.resolved_url == "https://www.worldbank.org/en/research/commodity-markets"
    assert len(res.retrieved_at_utc) >= 19


def test_per_host_throttle_applied_for_datagovmy() -> None:
    assert DEFAULT_HOST_INTERVALS["api.data.gov.my"] == 16.0
    clock = FakeClock()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(200, content=b"[]")

    with create_http_client(
        transport=httpx.MockTransport(handler),
        sleep_fn=clock.sleep,
        clock_fn=clock.clock,
    ) as client:
        # First call to api.data.gov.my: no sleep
        client.get("https://api.data.gov.my/data-catalogue?id=ppi_sitc")
        assert clock.sleeps == []

        # Advance clock by 4 seconds; second call to same host must sleep 12s (16 - 4)
        clock.now += 4.0
        client.get("https://api.data.gov.my/data-catalogue?id=trade_sitc_1d")
        assert clock.sleeps == [pytest.approx(12.0)]

        # Call to a different host (worldbank.org) does not sleep
        client.get("https://www.worldbank.org/en/research/commodity-markets")
        assert len(clock.sleeps) == 1

        # Advance 16 seconds; next call to api.data.gov.my does not need to sleep
        clock.now += 16.0
        client.get("https://api.data.gov.my/data-catalogue?id=sitc")
        assert len(clock.sleeps) == 1


def test_backoff_on_429_and_5xx_then_succeeds() -> None:
    clock = FakeClock()
    statuses = [429, 502, 503, 200]
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        status = statuses[attempts]
        attempts += 1
        return httpx.Response(status, content=b"payload" if status == 200 else b"retry")

    with create_http_client(
        transport=httpx.MockTransport(handler),
        max_retries=3,
        backoff_base=1.5,
        sleep_fn=clock.sleep,
        clock_fn=clock.clock,
    ) as client:
        resp = client.get("https://www.worldbank.org/data.xlsx")

    assert resp.status_code == 200
    assert resp.content == b"payload"
    assert attempts == 4
    # Exponential backoff: 1.5 * 2^0 = 1.5, 1.5 * 2^1 = 3.0, 1.5 * 2^2 = 6.0
    assert clock.sleeps == [pytest.approx(1.5), pytest.approx(3.0), pytest.approx(6.0)]


def test_retry_after_header_honoured_when_larger() -> None:
    clock = FakeClock()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "25"}, content=b"rate limited")
        return httpx.Response(200, content=b"ok")

    with create_http_client(
        transport=httpx.MockTransport(handler),
        host_intervals={"api.data.gov.my": 0.0},
        backoff_base=1.0,
        sleep_fn=clock.sleep,
        clock_fn=clock.clock,
    ) as client:
        resp = client.get("https://api.data.gov.my/data-catalogue?id=ppi_sitc")

    assert resp.status_code == 200
    assert attempts == 2
    assert clock.sleeps == [pytest.approx(25.0)]


def test_non_retryable_404_does_not_retry() -> None:
    clock = FakeClock()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, content=b"not found")

    with create_http_client(
        transport=httpx.MockTransport(handler),
        max_retries=3,
        sleep_fn=clock.sleep,
        clock_fn=clock.clock,
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_url(client, "https://www.worldbank.org/missing.xlsx")

    assert attempts == 1
    assert clock.sleeps == []


def test_exhausted_retries_raises_on_fetch_url() -> None:
    clock = FakeClock()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, content=b"unavailable")

    polite = PoliteTransport(
        httpx.MockTransport(handler),
        max_retries=2,
        backoff_base=0.5,
        sleep_fn=clock.sleep,
        clock_fn=clock.clock,
    )
    with create_http_client(transport=polite) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_url(client, "https://www.worldbank.org/down.xlsx")

    assert attempts == 3
    assert clock.sleeps == [pytest.approx(0.5), pytest.approx(1.0)]
