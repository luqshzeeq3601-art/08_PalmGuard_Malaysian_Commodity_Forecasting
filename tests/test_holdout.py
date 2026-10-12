"""Unit and integration tests for holdout evaluation and Gate G4 (Task T15)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from palmguard.holdout import run_holdout_scoring


def test_holdout_guard_enforcement() -> None:
    """Verify that holdout scoring cannot be executed twice without explicit override."""
    guard_path = Path("artifacts/champion/holdout_guard.json")
    assert guard_path.is_file(), "Guard file should already exist from formal holdout run"

    # Attempt second run without override -> must raise RuntimeError
    with pytest.raises(RuntimeError, match="Holdout was already scored"):
        run_holdout_scoring(override_exploratory=False)


def test_holdout_metrics_file_and_columns() -> None:
    """Verify reports/holdout_metrics.csv exists and contains required candidate models."""
    csv_path = Path("reports/holdout_metrics.csv")
    assert csv_path.is_file()

    df = pd.read_csv(csv_path)
    assert not df.empty

    expected_cols = {
        "series_id",
        "model",
        "split",
        "horizon",
        "n_eval",
        "mae",
        "rmse",
        "mase",
        "wape",
        "bias",
        "fit_failures",
    }
    assert expected_cols.issubset(set(df.columns))

    # All models must be represented in holdout
    assert set(df["model"].unique()) == {"B1", "B2", "B3", "B4", "M1", "M2"}
    assert set(df["series_id"].unique()) == {"palm_wb_myr", "ppi_oilsfats_my"}
    assert (df["split"] == "holdout").all()


def test_forecast_comparison_report_structure() -> None:
    """Verify reports/forecast_comparison.md contains mandatory statements and objective evaluations."""
    report_path = Path("reports/forecast_comparison.md")
    assert report_path.is_file()

    text = report_path.read_text(encoding="utf-8")
    # Verify mandatory statements from 05_FORECAST_EXPERIMENT_PLAN.md section 12
    assert "Forecasting demonstrator; not trading or investment advice" in text
    assert "No financial benefit was measured" in text
    assert "Interval coverage is empirical on historical data and is not guaranteed" in text
    assert "World Bank palm oil benchmark in MYR" in text

    # Verify objectives O2 and O3 evaluation sections
    assert "Objective O2" in text
    assert "Objective O3" in text
    assert "Limited Evidence" in text


def test_interval_coverage_reported_for_both_splits() -> None:
    """Verify Objective O3 is backed by measured coverage per horizon and level."""
    df = pd.concat(
        [
            pd.read_csv("reports/validation_coverage.csv"),
            pd.read_csv("reports/holdout_coverage.csv"),
        ]
    )
    assert set(df["split"].unique()) == {"validation", "holdout"}
    assert set(df["interval_method"].unique()) == {"C1", "C2"}
    selected = df[df["selected"]]
    # 2 series x 2 splits x 3 horizons x 2 levels
    assert len(selected) == 24
    assert selected["coverage"].between(0.0, 1.0).all()

    text = Path("reports/forecast_comparison.md").read_text(encoding="utf-8")
    assert "Objective O3 MET" in text or "Objective O3 MISSED" in text
