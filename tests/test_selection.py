"""Unit and integration tests for validation selection and Gate G3 (Task T14)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from palmguard.config import load_config
from palmguard.reporting import (
    FullSelectionRecord,
    execute_validation_selection,
    select_champion_and_interval,
    summarise_interval_coverage,
)


def test_validation_selection_execution(repo_copy: Path) -> None:
    """Verify execute_validation_selection produces all required artifacts with valid schemas."""
    record, metrics_df = execute_validation_selection()

    assert isinstance(record, FullSelectionRecord)
    assert len(record.series) == 2
    assert "palm_wb_myr" in record.series
    assert "ppi_oilsfats_my" in record.series

    # Check champion selection consistency
    palm_sel = record.series["palm_wb_myr"]
    assert palm_sel.champion_model in ["B1", "B4"]
    assert palm_sel.selected_interval_method in ["C1", "C2"]

    ppi_sel = record.series["ppi_oilsfats_my"]
    assert ppi_sel.champion_model == "B3"
    assert ppi_sel.selected_interval_method in ["C1", "C2"]

    # Check artifacts exist and parse cleanly
    sel_json = Path("artifacts/champion/selection_record.json")
    meta_json = Path("artifacts/champion/metadata.json")
    conf_json = Path("artifacts/champion/conformal_state.json")
    val_csv = Path("reports/validation_metrics.csv")
    preds_pq = Path("reports/predictions.parquet")

    assert sel_json.is_file()
    assert meta_json.is_file()
    assert conf_json.is_file()
    assert val_csv.is_file()
    assert preds_pq.is_file()

    # Verify JSON content
    data_sel = json.loads(sel_json.read_text(encoding="utf-8"))
    assert data_sel["project_name"] == "PalmGuard"
    assert "timestamp_utc" in data_sel

    # Verify CSV metrics format
    csv_df = pd.read_csv(val_csv)
    assert not csv_df.empty
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
    assert expected_cols.issubset(set(csv_df.columns))
    assert set(csv_df["horizon"].unique()) == {"1", "2", "3", "pooled"}


def test_champion_selection_tie_rule() -> None:
    """Verify that a simpler candidate wins when within 2% relative MASE."""
    cfg = load_config("config/project.yaml")

    # Synthetic prediction DataFrame with models B1 and B4
    # Suppose B4 has MASE 1.00 and B1 has MASE 1.01 (1% difference <= 2%)
    # B1 should be chosen due to simplicity order
    dates = pd.date_range("2020-01-01", periods=10, freq="MS").strftime("%Y-%m-%d").tolist()
    rows = []
    for d in dates:
        for h in [1, 2, 3]:
            # Actual = 100
            rows.append(
                {
                    "series_id": "palm_wb_myr",
                    "model": "B4",
                    "origin": d,
                    "target": d,
                    "horizon": h,
                    "actual": 100.0,
                    "prediction": 102.0,  # error 2.0
                    "fit_failed": False,
                }
            )
            rows.append(
                {
                    "series_id": "palm_wb_myr",
                    "model": "B1",
                    "origin": d,
                    "target": d,
                    "horizon": h,
                    "actual": 100.0,
                    "prediction": 102.02,  # error 2.02 (1% worse)
                    "fit_failed": False,
                }
            )

    pred_df = pd.DataFrame(rows)
    # Varying history so in-sample naive scale is positive (e.g. 2.0)
    panel_df = pd.DataFrame(
        [
            {"series_id": "palm_wb_myr", "month": d, "value": 100.0 + idx * 2.0}
            for idx, d in enumerate(dates)
        ]
    )

    sec_rec, _, _, _ = select_champion_and_interval("palm_wb_myr", pred_df, panel_df, cfg)
    assert sec_rec.champion_model == "B1"
    assert "simpler" in sec_rec.champion_reason.lower()


def test_coverage_error_is_gap_from_nominal() -> None:
    """Verify over-wide intervals are penalised: 100% coverage at 80% nominal is a 0.20 error."""
    intervals = pd.DataFrame(
        {
            "horizon": [1] * 10,
            "nominal_level": [0.80] * 10,
            "actual": [100.0] * 10,
            "lower_bound": [0.0] * 10,
            "upper_bound": [1000.0] * 10,
        }
    )
    cov = summarise_interval_coverage(intervals, "palm_wb_myr", "B1", "C1", "validation")
    assert cov["coverage"].iloc[0] == 1.0
    assert cov["coverage_error"].iloc[0] == pytest.approx(0.20)
    assert cov["n_eval"].iloc[0] == 10
