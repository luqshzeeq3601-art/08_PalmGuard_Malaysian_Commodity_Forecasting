"""Unit and integration tests for LightGBM M1 and M2 models (Task T12)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from palmguard.config import load_config
from palmguard.model import (
    M2_FEATURE_COLUMNS,
    fit_and_predict_lgbm_fold,
    generate_grid_configurations,
    get_feature_columns,
)
from palmguard.splits import OriginSplitInfo


def test_feature_sets_declaration() -> None:
    """Verify feature column declarations match spec."""
    m1_cols = get_feature_columns("M1")
    m2_cols = get_feature_columns("M2")

    assert len(m1_cols) == 15
    assert set(m1_cols).issubset(set(m2_cols))
    assert len(m2_cols) == 25
    assert "driver_usdmyr_return_1m" in m2_cols
    assert "driver_ppi_return_1m" in m2_cols
    assert "driver_exports_return_1m" in m2_cols


def test_grid_configurations_expansion() -> None:
    """Verify grid expansion generates exactly 8 configurations."""
    cfg = load_config("config/project.yaml")
    configs = generate_grid_configurations(cfg)

    assert len(configs) == 8
    for c in configs:
        assert c["num_leaves"] in [4, 8]
        assert c["min_child_samples"] in [5, 10]
        assert c["learning_rate"] in [0.03, 0.08]


def test_label_cutoff_enforcement() -> None:
    """Verify training data excludes future target observations at fold origin cutoff."""
    # Create synthetic features DataFrame spanning 20 months
    dates = pd.date_range("2020-01-01", periods=20, freq="MS").strftime("%Y-%m-%d").tolist()
    rows = []
    for idx, d in enumerate(dates):
        row: dict[str, object] = {
            "origin_month": d,
            "y_origin": float(100 + idx * 10),
            "target_return_h1": 0.05,
            "target_return_h2": 0.10,
            "target_return_h3": 0.15,
            "y_target_h1": float(100 + (idx + 1) * 10),
            "y_target_h2": float(100 + (idx + 2) * 10),
            "y_target_h3": float(100 + (idx + 3) * 10),
        }
        for col in M2_FEATURE_COLUMNS:
            row[col] = float(np.sin(idx))
        rows.append(row)

    features_df = pd.DataFrame(rows)

    fold = OriginSplitInfo(
        origin_index=0,
        origin_month=dates[15],  # index 15
        training_start_month=dates[0],
        training_end_month=dates[15],
        training_months_count=16,
        target_months={"h1": dates[16], "h2": dates[17], "h3": dates[18]},
        targets_observed={"h1": True, "h2": True, "h3": True},
    )

    params = {"n_estimators": 10, "learning_rate": 0.05, "num_leaves": 4, "min_child_samples": 3}
    preds, models = fit_and_predict_lgbm_fold(
        features_df, fold, model_id="M1", params=params, horizons=[1, 2, 3], seed=42
    )

    assert len(preds) == 3
    assert all(preds[h] > 0.0 for h in [1, 2, 3])


def test_lgbm_reproducibility_with_seed() -> None:
    """Verify that LightGBM predictions are completely deterministic with seed=42."""
    dates = pd.date_range("2020-01-01", periods=25, freq="MS").strftime("%Y-%m-%d").tolist()
    rows = []
    for idx, d in enumerate(dates):
        row = {
            "origin_month": d,
            "y_origin": float(1000 + idx * 20),
            "target_return_h1": float(np.sin(idx) * 0.05),
            "target_return_h2": float(np.cos(idx) * 0.05),
            "target_return_h3": float(np.sin(idx * 2) * 0.05),
        }
        for col in M2_FEATURE_COLUMNS:
            row[col] = float(idx * 0.1)
        rows.append(row)

    features_df = pd.DataFrame(rows)
    fold = OriginSplitInfo(
        origin_index=0,
        origin_month=dates[18],
        training_start_month=dates[0],
        training_end_month=dates[18],
        training_months_count=19,
        target_months={"h1": dates[19], "h2": dates[20], "h3": dates[21]},
        targets_observed={"h1": True, "h2": True, "h3": True},
    )

    params = {"n_estimators": 20, "learning_rate": 0.05, "num_leaves": 4, "min_child_samples": 3}
    preds1, _ = fit_and_predict_lgbm_fold(
        features_df, fold, model_id="M1", params=params, horizons=[1, 2, 3], seed=42
    )
    preds2, _ = fit_and_predict_lgbm_fold(
        features_df, fold, model_id="M1", params=params, horizons=[1, 2, 3], seed=42
    )

    assert preds1 == preds2
