"""Polite HTTP client with per-host throttling and exponential backoff retries."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_USER_AGENT = (
    "PalmGuard/0.1.0 (+https://github.com/palmguard; Malaysian commodity forecasting pipeline)"
)
DEFAULT_TIMEOUT = 30.0
DEFAULT_HOST_INTERVALS: dict[str, float] = {
    "api.data.gov.my": 16.0,
}
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class FetchResult:
    """Result of an HTTP GET request for raw snapshot ingestion."""

    request_url: str
    resolved_url: str
    http_status: int
    content: bytes
    retrieved_at_utc: str
    headers: dict[str, str]


class PoliteTransport(httpx.BaseTransport):
    """Transport wrapper applying per-host minimum intervals and retry backoff on 429/5xx."""

    def __init__(
        self,
        inner: httpx.BaseTransport,
        *,
        host_intervals: Mapping[str, float] | None = None,
        default_interval: float = 0.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        intervals = dict(DEFAULT_HOST_INTERVALS)
        if host_intervals is not None:
            intervals.update({k.lower(): float(v) for k, v in host_intervals.items()})
        self.host_intervals: dict[str, float] = {k.lower(): float(v) for k, v in intervals.items()}
        self.default_interval = float(default_interval)
        self.max_retries = int(max_retries)
        self.backoff_base = float(backoff_base)
        self._sleep_fn = sleep_fn
        self._clock_fn = clock_fn
        self._last_request_at: dict[str, float] = {}

    def _throttle(self, host: str) -> None:
        host_key = host.lower()
        min_interval = self.host_intervals.get(host_key, self.default_interval)
        if min_interval > 0.0 and host_key in self._last_request_at:
            elapsed = self._clock_fn() - self._last_request_at[host_key]
            if elapsed < min_interval:
                self._sleep_fn(min_interval - elapsed)
        self._last_request_at[host_key] = self._clock_fn()

    def _compute_backoff(self, attempt: int, response: httpx.Response) -> float:
        delay = self.backoff_base * (2**attempt)
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                parsed = float(retry_after)
                if parsed > 0:
                    delay = max(delay, parsed)
            except ValueError:
                pass
        return delay

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host or urlparse(str(request.url)).netloc
        self._throttle(host)

        for attempt in range(self.max_retries + 1):
            response = self._inner.handle_request(request)
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt >= self.max_retries:
                return response

            response.close()
            delay = self._compute_backoff(attempt, response)
            self._sleep_fn(delay)
            self._last_request_at[host.lower()] = self._clock_fn()

        return response  # pragma: no cover

    def close(self) -> None:
        self._inner.close()


def create_http_client(
    transport: httpx.BaseTransport | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    user_agent: str = DEFAULT_USER_AGENT,
    host_intervals: Mapping[str, float] | None = None,
    default_interval: float = 0.0,
    max_retries: int = 3,
    backoff_base: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock_fn: Callable[[], float] = time.monotonic,
    follow_redirects: bool = True,
) -> httpx.Client:
    """Create an httpx.Client configured with PoliteTransport, timeout and User-Agent."""
    inner = transport if transport is not None else httpx.HTTPTransport()
    if isinstance(inner, PoliteTransport):
        polite_transport = inner
    else:
        polite_transport = PoliteTransport(
            inner,
            host_intervals=host_intervals,
            default_interval=default_interval,
            max_retries=max_retries,
            backoff_base=backoff_base,
            sleep_fn=sleep_fn,
            clock_fn=clock_fn,
        )
    return httpx.Client(
        transport=polite_transport,
        timeout=httpx.Timeout(timeout),
        headers={"User-Agent": user_agent},
        follow_redirects=follow_redirects,
    )


def fetch_url(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    raise_for_status: bool = True,
) -> FetchResult:
    """Perform a GET request and return a structured FetchResult."""
    response = client.get(url, params=params)
    if raise_for_status:
        response.raise_for_status()
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return FetchResult(
        request_url=url,
        resolved_url=str(response.url),
        http_status=response.status_code,
        content=response.content,
        retrieved_at_utc=retrieved_at,
        headers={k.lower(): v for k, v in response.headers.items()},
    )
