"""Tests for data.gov.my bulk backfill, API query syntax, paging, and 429 retry (Task T04)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pandas as pd
import pytest

from palmguard.http import create_http_client
from palmguard.ingest.datagovmy import (
    EXCHANGERATES_BULK_URL,
    PPI_SITC_BULK_URL,
    TRADE_SITC_BULK_URL,
    build_catalogue_params,
    fetch_catalogue_records,
    ingest_datagovmy_dataset,
    parse_exchangerates,
    parse_ppi_sitc,
    parse_sitc_lookup,
    parse_trade_sitc,
)
from palmguard.ingest.snapshots import SnapshotValidationError


def test_build_catalogue_params_matches_official_syntax() -> None:
    params = build_catalogue_params(
        "ppi_sitc",
        filters={"series": "abs", "section": "4"},
        date_start="2026-01-01",
        date_end="2026-08-01",
        sort="date",
        limit=100,
    )
    assert params == {
        "id": "ppi_sitc",
        "filter": "abs@series,4@section",
        "date_start": "2026-01-01@date",
        "date_end": "2026-08-01@date",
        "sort": "date",
        "limit": "100",
    }


def test_paging_and_429_retry_on_catalogue_api() -> None:
    seen_queries: list[dict[str, str]] = []
    sleeps: list[float] = []
    clock_now = 50.0
    call_count = 0

    def fake_clock() -> float:
        return clock_now

    def fake_sleep(sec: float) -> None:
        nonlocal clock_now
        sleeps.append(sec)
        clock_now += sec

    page1 = [
        {"date": "2026-06-01", "series": "abs", "section": "4", "index": 135.0},
        {"date": "2026-07-01", "series": "abs", "section": "4", "index": 136.2},
    ]
    page2 = [
        {"date": "2026-08-01", "series": "abs", "section": "4", "index": 138.4},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        q = dict(request.url.params)
        seen_queries.append(q)
        # First call returns 429 Too Many Requests
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "16"}, content=b"rate limited")
        if q.get("date_start") == "2026-06-01@date":
            return httpx.Response(200, content=json.dumps(page1).encode("utf-8"))
        if q.get("date_start") == "2026-07-02@date":
            return httpx.Response(200, content=json.dumps(page2).encode("utf-8"))
        return httpx.Response(200, content=b"[]")

    with create_http_client(
        transport=httpx.MockTransport(handler),
        sleep_fn=fake_sleep,
        clock_fn=fake_clock,
    ) as client:
        records, _, status = fetch_catalogue_records(
            client,
            "ppi_sitc",
            filters={"series": "abs", "section": "4"},
            date_start="2026-06-01",
            page_size=2,
        )

    assert status == 200
    assert len(records) == 3
    assert [r["date"] for r in records] == ["2026-06-01", "2026-07-01", "2026-08-01"]
    assert seen_queries[0]["filter"] == "abs@series,4@section"
    assert seen_queries[0]["date_start"] == "2026-06-01@date"
    assert seen_queries[-1]["date_start"] == "2026-07-02@date"
    # First sleep is 16s from 429 Retry-After, second sleep is 16s host throttle before page 2
    assert sleeps == [pytest.approx(16.0), pytest.approx(16.0)]


def test_backfill_then_incremental_for_ppi_and_other_datasets(tmp_path: Path) -> None:
    ppi_csv = (
        "series,date,section,index\n"
        "abs,2026-06-01,4,135.0\n"
        "abs,2026-07-01,4,136.2\n"
        "growth_yoy,2026-07-01,4,3.1\n"
    ).encode("utf-8")

    exr_df = pd.DataFrame(
        {
            "date": ["2026-07-01", "2026-07-01", "2026-07-02"],
            "rate_type": ["buying", "middle", "middle"],
            "USD": [4.40, 4.42, 4.43],
        }
    )
    exr_buf = io.BytesIO()
    exr_df.to_parquet(exr_buf, index=False)

    trade_df = pd.DataFrame(
        {
            "date": ["2026-06-01", "2026-07-01"],
            "section": ["4", "4"],
            "exports": [7500.0, 7800.0],
            "imports": [1200.0, 1150.0],
        }
    )
    trade_buf = io.BytesIO()
    trade_df.to_parquet(trade_buf, index=False)

    sitc_json = json.dumps(
        [
            {"digits": 1, "section": "0", "desc_en": "Food"},
            {"digits": 1, "section": "4", "desc_en": "Animal and vegetable oils, and fats"},
        ]
    ).encode("utf-8")

    api_ppi_update = json.dumps(
        [
            {"series": "abs", "date": "2026-07-01", "section": "4", "index": 136.5},
            {"series": "abs", "date": "2026-08-01", "section": "4", "index": 138.0},
        ]
    ).encode("utf-8")

    seen_api_params: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == PPI_SITC_BULK_URL:
            return httpx.Response(200, content=ppi_csv)
        if url == EXCHANGERATES_BULK_URL:
            return httpx.Response(200, content=exr_buf.getvalue())
        if url == TRADE_SITC_BULK_URL:
            return httpx.Response(200, content=trade_buf.getvalue())
        if request.url.host == "api.data.gov.my":
            params = dict(request.url.params)
            seen_api_params.append(params)
            if params.get("id") == "sitc":
                return httpx.Response(200, content=sitc_json)
            if params.get("id") == "ppi_sitc":
                return httpx.Response(200, content=api_ppi_update)
        return httpx.Response(404)

    with create_http_client(
        transport=httpx.MockTransport(handler),
        host_intervals={"api.data.gov.my": 0.0},
    ) as client:
        # 1. Backfill runs (auto mode with empty raw_root uses bulk URLs)
        r_exr = ingest_datagovmy_dataset(
            tmp_path,
            client,
            "exchangerates_daily_1700",
            retrieved_at_utc="2026-10-11T08:00:00+00:00",
        )
        r_ppi_1 = ingest_datagovmy_dataset(
            tmp_path,
            client,
            "ppi_sitc",
            retrieved_at_utc="2026-10-11T08:00:00+00:00",
        )
        r_trade = ingest_datagovmy_dataset(
            tmp_path,
            client,
            "trade_sitc_1d",
            retrieved_at_utc="2026-10-11T08:00:00+00:00",
        )
        r_sitc = ingest_datagovmy_dataset(
            tmp_path,
            client,
            "sitc",
            retrieved_at_utc="2026-10-11T08:00:00+00:00",
        )

        # 2. Next run on ppi_sitc in auto mode uses incremental API with inferred date_start
        r_ppi_2 = ingest_datagovmy_dataset(
            tmp_path,
            client,
            "ppi_sitc",
            retrieved_at_utc="2026-10-12T08:00:00+00:00",
        )

    assert r_exr.manifest.row_count == 2
    assert r_ppi_1.manifest.row_count == 2
    assert r_trade.manifest.row_count == 2
    assert r_sitc.manifest.row_count == 2

    # Incremental update merged 2026-06-01, revised 2026-07-01 (136.5), and added 2026-08-01 (138.0)
    assert r_ppi_2.status == "written"
    assert r_ppi_2.manifest.row_count == 3
    parsed_ppi = parse_ppi_sitc(r_ppi_2.payload_path.read_bytes(), r_ppi_2.manifest.filename)
    assert list(parsed_ppi["value"]) == [
        pytest.approx(135.0),
        pytest.approx(136.5),
        pytest.approx(138.0),
    ]
    assert any(p.get("id") == "ppi_sitc" and "date_start" in p for p in seen_api_params)


def test_parsers_reject_invalid_payloads() -> None:
    with pytest.raises(SnapshotValidationError):
        parse_exchangerates(
            b'[{"date": "2026-01-01", "rate_type": "middle", "USD": -4.2}]', "x.json"
        )

    with pytest.raises(SnapshotValidationError):
        parse_ppi_sitc(b"series,date,section\nabs,2026-01-01,4\n", "x.csv")

    with pytest.raises(SnapshotValidationError):
        parse_trade_sitc(
            b'[{"date": "2026-01-01", "section": "4", "exports": 0, "imports": 10}]', "x.json"
        )

    with pytest.raises(SnapshotValidationError):
        parse_sitc_lookup(b'[{"section": "0", "desc_en": "Food"}]')
