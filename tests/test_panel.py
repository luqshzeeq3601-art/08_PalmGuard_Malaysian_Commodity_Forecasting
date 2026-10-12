"""Tests for monthly panel query and DuckDB feature builder (Task T07)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from palmguard.contracts import validate_monthly_series_df
from palmguard.features import build_monthly_panel_df
from palmguard.ingest.snapshots import SnapshotManifest, compute_sha256


def _write_mock_manifest(dir_path: Path, manifest: SnapshotManifest) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "manifest.json").write_text(
        json.dumps(manifest.model_dump(), indent=2), encoding="utf-8"
    )


@pytest.fixture
def mock_raw_store(tmp_path: Path) -> Path:
    """Create a mock raw snapshot directory tree with controlled vintages."""
    raw_root = tmp_path / "raw"

    # 1. World Bank Pink Sheet (dummy csv/xlsx)
    # 2026-05-01 vintage
    wb_v1_dir = raw_root / "worldbank" / "pink_sheet" / "retrieved=2026-05-01"
    wb_v1_dir.mkdir(parents=True, exist_ok=True)
    wb_file = wb_v1_dir / "pink_sheet.xlsx"
    wb_file.write_bytes(b"placeholder")
    _write_mock_manifest(
        wb_v1_dir,
        SnapshotManifest(
            source="worldbank",
            dataset="pink_sheet",
            request_url="https://mock.example.com/pink_sheet.xlsx",
            resolved_url="https://mock.example.com/pink_sheet.xlsx",
            http_status=200,
            retrieved_at_utc="2026-05-01T00:00:00Z",
            sha256="a" * 64,
            bytes=11,
            schema_version="1.0",
            row_count=10,
            snapshot_id="worldbank.pink_sheet.2026-05-01.aaaa",
            filename="pink_sheet.xlsx",
        ),
    )

    # 2. BNM Exchange Rates (daily middle rate)
    bnm_dir = raw_root / "bnm" / "exchangerates_daily_1700" / "retrieved=2026-05-01"
    bnm_dir.mkdir(parents=True, exist_ok=True)
    bnm_csv = bnm_dir / "data.csv"
    bnm_content = (
        "date,currency,rate_type,rate\n"
        "2026-04-01,USD,middle,4.50\n"
        "2026-04-15,USD,middle,4.50\n"
        "2026-04-28,USD,middle,4.50\n"
        "2026-05-02,USD,middle,4.60\n"
    )
    bnm_csv.write_text(bnm_content, encoding="utf-8")
    _write_mock_manifest(
        bnm_dir,
        SnapshotManifest(
            source="bnm",
            dataset="exchangerates_daily_1700",
            request_url="https://mock.example.com/exr.csv",
            resolved_url="https://mock.example.com/exr.csv",
            http_status=200,
            retrieved_at_utc="2026-05-01T00:00:00Z",
            sha256=compute_sha256(bnm_content.encode("utf-8")),
            bytes=len(bnm_content),
            schema_version="1.0",
            row_count=4,
            snapshot_id="bnm.exchangerates_daily_1700.2026-05-01.test",
            filename="data.csv",
        ),
    )

    return raw_root


def test_hand_computed_reconciliation() -> None:
    """Verify hand-computed USD/MYR average and palm_wb_myr conversion via DuckDB."""
    conn = duckdb.connect(":memory:")

    # Setup synthetic tables
    manifest_df = pd.DataFrame(
        [
            {
                "source": "worldbank",
                "dataset": "pink_sheet",
                "snapshot_id": "wb_snap",
                "available_from": "2026-05-01",
            },
            {
                "source": "bnm",
                "dataset": "exchangerates_daily_1700",
                "snapshot_id": "bnm_snap",
                "available_from": "2026-05-01",
            },
            {
                "source": "dosm",
                "dataset": "ppi_sitc",
                "snapshot_id": "ppi_snap",
                "available_from": "2026-05-01",
            },
            {
                "source": "dosm",
                "dataset": "trade_sitc_1d",
                "snapshot_id": "trd_snap",
                "available_from": "2026-05-01",
            },
        ]
    )
    conn.register("raw_manifests", manifest_df)

    # April 2026 daily rates: 4.0, 4.2, 4.4 -> Mean = 4.20
    # Day 28 >= 25 so April 2026 is considered a completed trading month
    fx_df = pd.DataFrame(
        [
            {"date": "2026-04-02", "rate_type": "middle", "USD": 4.00},
            {"date": "2026-04-15", "rate_type": "middle", "USD": 4.20},
            {"date": "2026-04-28", "rate_type": "middle", "USD": 4.40},
            # May 2026 incomplete (only day 2) -> excluded from complete_fx_monthly
            {"date": "2026-05-02", "rate_type": "middle", "USD": 5.00},
        ]
    )
    conn.register("raw_exchangerates", fx_df)

    # WB Pink Sheet April 2026 palm oil USD = 1000.0 $/mt
    wb_df = pd.DataFrame(
        [
            {"series_id": "palm_wb_usd", "month": "2026-04-01", "value": 1000.0},
            {"series_id": "brent_wb_usd", "month": "2026-04-01", "value": 85.0},
        ]
    )
    conn.register("raw_pink_sheet", wb_df)

    # DOSM dummy
    conn.register(
        "raw_ppi",
        pd.DataFrame([{"series": "abs", "date": "2026-03-01", "section": "4", "index": 120.5}]),
    )
    conn.register(
        "raw_trade",
        pd.DataFrame([{"date": "2026-02-01", "section": "4", "exports": 5500.0, "imports": 200.0}]),
    )

    sql_text = Path("queries/monthly_panel.sql").read_text(encoding="utf-8")
    result_df = conn.execute(sql_text, {"as_of": "2026-05-08"}).df()

    # Checks
    assert not result_df.empty

    # 1. USD/MYR average check
    fx_row = result_df[result_df["series_id"] == "usdmyr_avg"]
    assert len(fx_row) == 1
    assert fx_row.iloc[0]["month"] == "2026-04-01"
    assert pytest.approx(fx_row.iloc[0]["value"], rel=1e-5) == 4.20

    # 2. palm_wb_myr conversion check: 1000.0 * 4.20 = 4200.0
    palm_myr_row = result_df[result_df["series_id"] == "palm_wb_myr"]
    assert len(palm_myr_row) == 1
    assert palm_myr_row.iloc[0]["month"] == "2026-04-01"
    assert pytest.approx(palm_myr_row.iloc[0]["value"], rel=1e-5) == 4200.0

    # 3. Series validation passes
    for s_id in result_df["series_id"].unique():
        validate_monthly_series_df(
            result_df[result_df["series_id"] == s_id].reset_index(drop=True),
            expected_series_id=s_id,
            min_rows=1,
        )


def test_vintage_isolation() -> None:
    """Verify that snapshots or records with available_from > $as_of are excluded by SQL."""
    conn = duckdb.connect(":memory:")

    manifest_df = pd.DataFrame(
        [
            {
                "source": "worldbank",
                "dataset": "pink_sheet",
                "snapshot_id": "wb_snap_v1",
                "available_from": "2026-04-01",
            },
            {
                "source": "worldbank",
                "dataset": "pink_sheet",
                "snapshot_id": "wb_snap_v2",
                "available_from": "2026-06-01",
            },
            {
                "source": "bnm",
                "dataset": "exchangerates_daily_1700",
                "snapshot_id": "bnm_snap",
                "available_from": "2026-04-01",
            },
            {
                "source": "dosm",
                "dataset": "ppi_sitc",
                "snapshot_id": "ppi_snap",
                "available_from": "2026-04-01",
            },
            {
                "source": "dosm",
                "dataset": "trade_sitc_1d",
                "snapshot_id": "trd_snap",
                "available_from": "2026-04-01",
            },
        ]
    )
    conn.register("raw_manifests", manifest_df)

    # If as_of is 2026-05-01, v2 is strictly in the future and should be excluded
    fx_df = pd.DataFrame([{"date": "2026-03-28", "rate_type": "middle", "USD": 4.50}])
    conn.register("raw_exchangerates", fx_df)

    wb_df = pd.DataFrame([{"series_id": "palm_wb_usd", "month": "2026-03-01", "value": 1050.0}])
    conn.register("raw_pink_sheet", wb_df)

    conn.register(
        "raw_ppi",
        pd.DataFrame([{"series": "abs", "date": "2026-02-01", "section": "4", "index": 115.0}]),
    )
    conn.register(
        "raw_trade",
        pd.DataFrame([{"date": "2026-01-01", "section": "4", "exports": 5000.0, "imports": 100.0}]),
    )

    sql_text = Path("queries/monthly_panel.sql").read_text(encoding="utf-8")
    result_df = conn.execute(sql_text, {"as_of": "2026-05-01"}).df()

    palm_row = result_df[result_df["series_id"] == "palm_wb_usd"].iloc[0]
    # Should use v1 snapshot, not future v2
    assert "wb_snap_v1" in str(palm_row["snapshot_id"])
    assert "wb_snap_v2" not in str(palm_row["snapshot_id"])


def test_live_data_build_monthly_panel() -> None:
    """Integration test running build_monthly_panel_df against committed live snapshots."""
    raw_root = Path("data/raw")
    if not (raw_root / "worldbank" / "pink_sheet").exists():
        pytest.skip("data/raw not present")

    df = build_monthly_panel_df(raw_root=raw_root, as_of="2026-10-11")
    assert not df.empty
    expected_series = {
        "palm_wb_usd",
        "brent_wb_usd",
        "soyoil_wb_usd",
        "usdmyr_avg",
        "palm_wb_myr",
        "ppi_oilsfats_my",
        "exports_sitc4",
    }
    present_series = set(df["series_id"].unique())
    assert expected_series.issubset(present_series)

    # Check palm_wb_myr spans >= 280 months
    palm_myr = df[df["series_id"] == "palm_wb_myr"]
    assert len(palm_myr) >= 280
