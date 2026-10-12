"""Leakage tests and feature contract verification for DuckDB feature SQL (Task T08)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from palmguard.features import build_features_df, build_monthly_panel_df

# Feature column sets
OWN_FEATURE_COLUMNS = [
    "return_lag1",
    "return_lag2",
    "return_lag3",
    "return_lag6",
    "return_lag12",
    "return_roll_mean_3m",
    "return_roll_std_3m",
    "return_roll_mean_6m",
    "return_roll_std_6m",
    "return_roll_mean_12m",
    "return_roll_std_12m",
    "pct_dist_from_12m_max",
    "pct_dist_from_12m_min",
    "origin_month_num",
    "origin_quarter",
]

DRIVER_FEATURE_COLUMNS = [
    "driver_usdmyr_return_1m",
    "driver_usdmyr_roll_mean_3m",
    "driver_brent_return_1m",
    "driver_brent_roll_mean_3m",
    "driver_soyoil_return_1m",
    "driver_soyoil_roll_mean_3m",
    "driver_ppi_return_1m",
    "driver_ppi_roll_mean_3m",
    "driver_exports_return_1m",
    "driver_exports_roll_mean_3m",
]

ALL_FEATURE_COLUMNS = OWN_FEATURE_COLUMNS + DRIVER_FEATURE_COLUMNS


@pytest.fixture
def synthetic_panel_df() -> pd.DataFrame:
    """Generate 36 contiguous months of synthetic data across all series."""
    dates = pd.date_range("2023-01-01", periods=36, freq="MS").strftime("%Y-%m-01")
    rows: list[dict[str, object]] = []

    # Simple geometric sequence for palm_wb_myr: 3000 * 1.01^i
    for i, dt in enumerate(dates):
        palm_val = 3000.0 * (1.02**i)
        usdmyr_val = 4.20 + 0.01 * (i % 5)
        brent_val = 80.0 + 0.5 * (i % 6)
        soyoil_val = 1100.0 + 10.0 * (i % 4)
        ppi_val = 100.0 + 0.2 * i
        exports_val = 5000.0 + 50.0 * i

        rows.append(
            {
                "series_id": "palm_wb_myr",
                "month": dt,
                "value": palm_val,
                "available_from": dt,
                "snapshot_id": "snap",
                "is_provisional": False,
            }
        )
        rows.append(
            {
                "series_id": "usdmyr_avg",
                "month": dt,
                "value": usdmyr_val,
                "available_from": dt,
                "snapshot_id": "snap",
                "is_provisional": False,
            }
        )
        rows.append(
            {
                "series_id": "brent_wb_usd",
                "month": dt,
                "value": brent_val,
                "available_from": dt,
                "snapshot_id": "snap",
                "is_provisional": False,
            }
        )
        rows.append(
            {
                "series_id": "soyoil_wb_usd",
                "month": dt,
                "value": soyoil_val,
                "available_from": dt,
                "snapshot_id": "snap",
                "is_provisional": False,
            }
        )
        rows.append(
            {
                "series_id": "ppi_oilsfats_my",
                "month": dt,
                "value": ppi_val,
                "available_from": dt,
                "snapshot_id": "snap",
                "is_provisional": False,
            }
        )
        rows.append(
            {
                "series_id": "exports_sitc4",
                "month": dt,
                "value": exports_val,
                "available_from": dt,
                "snapshot_id": "snap",
                "is_provisional": False,
            }
        )

    return pd.DataFrame(rows)


def test_static_sql_no_following() -> None:
    """Verify that features.sql contains NO 'FOLLOWING' window clauses except in comments or leads."""
    sql_text = Path("queries/features.sql").read_text(encoding="utf-8")
    # Strip SQL single line comments
    lines = [line.split("--")[0] for line in sql_text.splitlines()]
    clean_sql = "\n".join(lines).upper()

    # The word FOLLOWING must never appear in any window frame definition
    assert "FOLLOWING" not in clean_sql


def test_future_mutation_leakage_invariance(synthetic_panel_df: pd.DataFrame) -> None:
    """O4 Leakage Test: Mutating future data at t+k must NOT change feature values at t."""
    df_clean = build_features_df(synthetic_panel_df, target_series="palm_wb_myr")

    # Pick an origin t in the middle (e.g. index 20, corresponding to month 20)
    origin_idx = 20
    origin_row_before = df_clean.iloc[origin_idx].to_dict()
    origin_month = origin_row_before["origin_month"]

    # Now create a mutated panel where months strictly > origin_month are corrupted / 10x-ed
    mutated_panel = synthetic_panel_df.copy()
    future_mask = mutated_panel["month"] > origin_month
    mutated_panel.loc[future_mask, "value"] = mutated_panel.loc[future_mask, "value"] * 10.0

    df_mutated = build_features_df(mutated_panel, target_series="palm_wb_myr")
    origin_row_after = df_mutated[df_mutated["origin_month"] == origin_month].iloc[0].to_dict()

    # Check that EVERY feature column in ALL_FEATURE_COLUMNS at origin t is strictly identical
    for col in ALL_FEATURE_COLUMNS:
        val_before = origin_row_before[col]
        val_after = origin_row_after[col]
        if pd.isna(val_before) and pd.isna(val_after):
            continue
        assert pytest.approx(val_before, rel=1e-6) == val_after, (
            f"Feature {col} changed at origin {origin_month} when future was mutated!"
        )

    # Conversely, ground truth future labels (y_target_h1, target_return_h1) MUST have changed because future changed
    assert origin_row_after["y_target_h1"] != origin_row_before["y_target_h1"]


def test_hand_calculated_feature_windows() -> None:
    """Verify exact hand-calculated returns and rolling statistics."""
    # Create simple sequence: values = [100.0, 110.0, 121.0, 133.1]
    # monthly returns: r1 = ln(110/100) = 0.095310, r2 = ln(121/110) = 0.095310, r3 = ln(133.1/121) = 0.095310
    months = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]
    vals = [100.0, 110.0, 121.0, 133.1]
    rows = [
        {
            "series_id": "palm_wb_myr",
            "month": m,
            "value": v,
            "available_from": m,
            "snapshot_id": "s",
            "is_provisional": False,
        }
        for m, v in zip(months, vals)
    ]
    panel_df = pd.DataFrame(rows)

    feats_df = build_features_df(panel_df, target_series="palm_wb_myr")
    # For month 4 (2026-04-01):
    m4 = feats_df[feats_df["origin_month"] == "2026-04-01"].iloc[0]
    expected_r = np.log(1.1)

    assert pytest.approx(m4["return_lag1"], rel=1e-5) == expected_r
    assert pytest.approx(m4["return_lag2"], rel=1e-5) == expected_r
    assert pytest.approx(m4["return_lag3"], rel=1e-5) == expected_r
    assert pytest.approx(m4["return_roll_mean_3m"], rel=1e-5) == expected_r
    # Since r is constant, standard deviation of 3-month window is 0.0
    assert pytest.approx(m4["return_roll_std_3m"], abs=1e-6) == 0.0


def test_publication_lag_alignment() -> None:
    """Verify that driver features enforce respective publication lags (lag 1, lag 2, lag 3)."""
    # Build a minimal panel where value = YYYYMM integer so we can track exact month sources
    months = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
    rows: list[dict[str, object]] = []
    for m in months:
        # e.g. 2026-01-01 -> 1.0, 2026-02-01 -> 2.0, etc.
        idx = int(m[5:7])
        rows.append(
            {
                "series_id": "palm_wb_myr",
                "month": m,
                "value": float(idx * 100),
                "available_from": m,
                "snapshot_id": "s",
                "is_provisional": False,
            }
        )
        rows.append(
            {
                "series_id": "usdmyr_avg",
                "month": m,
                "value": float(idx * 10),
                "available_from": m,
                "snapshot_id": "s",
                "is_provisional": False,
            }
        )
        rows.append(
            {
                "series_id": "ppi_oilsfats_my",
                "month": m,
                "value": float(idx * 20),
                "available_from": m,
                "snapshot_id": "s",
                "is_provisional": False,
            }
        )
        rows.append(
            {
                "series_id": "exports_sitc4",
                "month": m,
                "value": float(idx * 30),
                "available_from": m,
                "snapshot_id": "s",
                "is_provisional": False,
            }
        )

    panel_df = pd.DataFrame(rows)
    feats = build_features_df(panel_df, target_series="palm_wb_myr")

    # At origin 2026-04-01:
    # - USD/MYR has lag 1 -> latest usable is 2026-04-01: return between 04 and 03 = ln(40/30) = ln(4/3)
    # - PPI has lag 2 -> latest usable is 2026-03-01: return between 03 and 02 = ln(60/40) = ln(3/2)
    # - Exports has lag 3 -> latest usable is 2026-02-01: return between 02 and 01 = ln(60/30) = ln(2/1)
    row_apr = feats[feats["origin_month"] == "2026-04-01"].iloc[0]

    assert pytest.approx(row_apr["driver_usdmyr_return_1m"], rel=1e-5) == np.log(40.0 / 30.0)
    assert pytest.approx(row_apr["driver_ppi_return_1m"], rel=1e-5) == np.log(60.0 / 40.0)
    assert pytest.approx(row_apr["driver_exports_return_1m"], rel=1e-5) == np.log(60.0 / 30.0)


def test_calendar_sql_generation() -> None:
    """Verify queries/calendar.sql expands horizons 1..3 with exact date arithmetic."""
    conn = duckdb.connect(":memory:")
    conn.register("calendar_origins", pd.DataFrame([{"origin_month_str": "2026-04-01"}]))
    sql_text = Path("queries/calendar.sql").read_text(encoding="utf-8")
    cal_df = conn.execute(sql_text).df()

    assert len(cal_df) == 3
    assert cal_df["origin_month"].tolist() == ["2026-04-01", "2026-04-01", "2026-04-01"]
    assert cal_df["horizon"].tolist() == [1, 2, 3]
    assert cal_df["target_month"].tolist() == ["2026-05-01", "2026-06-01", "2026-07-01"]
    assert cal_df["origin_month_num"].tolist() == [4, 4, 4]
    assert cal_df["target_month_num"].tolist() == [5, 6, 7]


def test_live_data_feature_generation() -> None:
    """Verify build_features_df on live monthly panel."""
    raw_root = Path("data/raw")
    if not (raw_root / "worldbank" / "pink_sheet").exists():
        pytest.skip("data/raw not present")

    panel_df = build_monthly_panel_df(raw_root=raw_root, as_of="2026-10-11")
    features_df = build_features_df(panel_df, target_series="palm_wb_myr")

    assert not features_df.empty
    assert len(features_df) >= 280
    assert set(ALL_FEATURE_COLUMNS).issubset(set(features_df.columns))

    # Check that tail features for recent months (e.g. 2026-09) have finite values
    recent = features_df.iloc[-1]
    assert np.isfinite(recent["return_lag1"])
    assert np.isfinite(recent["return_roll_mean_3m"])
    assert np.isfinite(recent["driver_usdmyr_return_1m"])
    assert np.isfinite(recent["driver_ppi_return_1m"])
    assert np.isfinite(recent["driver_exports_return_1m"])
