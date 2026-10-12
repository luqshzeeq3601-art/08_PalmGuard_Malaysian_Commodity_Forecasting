"""Tests for rolling monitoring metrics and the scoring query (Task T17)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from palmguard.config import load_config
from palmguard.monitoring import evaluate_series_monitoring


def test_rolling_metrics_match_hand_calculation() -> None:
    """Verify 12- and 24-month rolling means use only the trailing window of scored forecasts."""
    cfg = load_config("config/project.yaml")
    months = pd.date_range("2024-01-01", periods=24, freq="MS").strftime("%Y-%m-%d")
    # First 12 months: scaled error 2.0 and every 80% interval missed.
    # Last 12 months: scaled error 1.0 and 9 of 12 intervals hit.
    scores = pd.DataFrame(
        {
            "series_id": "palm_wb_myr",
            "target_month": months,
            "horizon": 1,
            "mase": [2.0] * 12 + [1.0] * 12,
            "abs_pct_error": [0.10] * 12 + [0.05] * 12,
            "interval_hit_80": [0] * 12 + [1] * 9 + [0] * 3,
            "interval_hit_90": [1] * 24,
        }
    )

    report = evaluate_series_monitoring(
        "palm_wb_myr", scores, pd.DataFrame(), cfg, "B1", "C2", "2026-01-01T00:00:00+00:00"
    )
    h1 = report.horizons[1]

    assert h1.observations_count == 24
    assert h1.rolling_12m_mase == pytest.approx(1.0)
    assert h1.rolling_24m_mase == pytest.approx(1.5)
    assert h1.rolling_12m_mape == pytest.approx(0.05)
    assert h1.rolling_24m_mape == pytest.approx(0.075)
    assert h1.rolling_12m_coverage_80 == pytest.approx(9 / 12)
    assert h1.rolling_24m_coverage_80 == pytest.approx(9 / 24)
    assert h1.rolling_24m_coverage_90 == pytest.approx(1.0)
    assert report.latest_evaluated_target_month == "2025-12-01"
    assert report.horizons[2].observations_count == 0


def test_scoring_query_errors_hits_and_scaled_error() -> None:
    """Verify scoring.sql against a hand-computed forecast, with the scale cut at the origin."""
    panel = pd.DataFrame(
        {
            "series_id": "palm_wb_myr",
            "month": ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01", "2024-05-01"],
            # one-step changes: 10, 20, 30, then 400 after the origin
            "value": [100.0, 110.0, 130.0, 160.0, 560.0],
        }
    )
    ledger = pd.DataFrame(
        [
            {
                "series_id": "palm_wb_myr",
                "model_id": "B1",
                "origin_month": "2024-03-01",
                "target_month": "2024-04-01",
                "horizon": 1,
                "model_version": "test",
                "y_pred": 130.0,
                "q80_lower": 120.0,
                "q80_upper": 140.0,
                "q90_lower": 100.0,
                "q90_upper": 160.0,
                "forecast_timestamp_utc": "2024-03-08T00:00:00+00:00",
            },
            {
                # target not observed yet: must not be scored
                "series_id": "palm_wb_myr",
                "model_id": "B1",
                "origin_month": "2024-05-01",
                "target_month": "2024-06-01",
                "horizon": 1,
                "model_version": "test",
                "y_pred": 560.0,
                "q80_lower": 500.0,
                "q80_upper": 600.0,
                "q90_lower": 480.0,
                "q90_upper": 620.0,
                "forecast_timestamp_utc": "2024-05-08T00:00:00+00:00",
            },
        ]
    )

    con = duckdb.connect()
    con.register("forecast_ledger", ledger)
    con.register("monthly_panel", panel)
    scored = con.sql(Path("queries/scoring.sql").read_text(encoding="utf-8")).df()
    con.close()

    assert len(scored) == 1
    row = scored.iloc[0]
    assert row["y_actual"] == pytest.approx(160.0)
    assert row["abs_error"] == pytest.approx(30.0)
    assert row["abs_pct_error"] == pytest.approx(30.0 / 160.0)
    # scale uses changes up to the origin only: mean(10, 20) = 15
    assert row["mase"] == pytest.approx(30.0 / 15.0)
    assert row["interval_hit_80"] == 0
    assert row["interval_hit_90"] == 1
