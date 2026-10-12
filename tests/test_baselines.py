"""Unit and integration tests for baselines B1-B4 (Task T11)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from palmguard.baselines import (
    backtest_baselines,
    forecast_arima_b4,
    forecast_ets_b3,
    forecast_naive_b1,
    forecast_seasonal_naive_b2,
    select_best_arima_order,
)
from palmguard.splits import OriginSplitInfo


def test_forecast_naive_b1() -> None:
    """Verify B1 naive repeats the latest observed value across all horizons."""
    history = [100.0, 150.0, 200.0]
    preds = forecast_naive_b1(history, horizons=[1, 2, 3])
    assert preds == {1: 200.0, 2: 200.0, 3: 200.0}

    with pytest.raises(ValueError, match="empty history"):
        forecast_naive_b1([], horizons=[1, 2, 3])


def test_forecast_seasonal_naive_b2() -> None:
    """Verify B2 seasonal naive matches y[t+h-12]."""
    # 24 months of monthly values = month index 1..24
    history = list(range(1, 25))  # len 24, last is 24
    # For h=1: t+1-12 = 24+1-12 = 13 (value 13)
    # For h=2: t+2-12 = 24+2-12 = 14 (value 14)
    # For h=3: t+3-12 = 24+3-12 = 15 (value 15)
    preds = forecast_seasonal_naive_b2(history, horizons=[1, 2, 3], seasonal_period=12)
    assert preds == {1: 13.0, 2: 14.0, 3: 15.0}

    # Short history fallback to naive:
    short_history = [50.0, 60.0]
    preds_fallback = forecast_seasonal_naive_b2(short_history, horizons=[1, 2, 3])
    assert preds_fallback == {1: 60.0, 2: 60.0, 3: 60.0}


def test_forecast_ets_b3_and_fallback() -> None:
    """Verify B3 ETS produces valid positive predictions and falls back to B1 on invalid data."""
    # Monotonic positive series
    history = np.linspace(1000.0, 2000.0, 40)
    preds, failed, reason = forecast_ets_b3(history, horizons=[1, 2, 3])
    assert not failed
    assert reason is None
    assert all(preds[h] > 1000.0 for h in [1, 2, 3])

    # Non-positive history causes immediate fallback to B1
    bad_history = np.array([-10.0, 0.0, 10.0, 20.0])
    fallback_preds, failed_fb, reason_fb = forecast_ets_b3(bad_history, horizons=[1, 2, 3])
    assert failed_fb is True
    assert "Non-positive" in (reason_fb or "")
    assert fallback_preds[1] == 20.0  # last observed value (B1)


def test_forecast_arima_b4_and_fallback() -> None:
    """Verify B4 ARIMA works for both (0,1,1) and (1,1,0) orders and falls back to B1 on error."""
    history = np.linspace(100.0, 200.0, 30)
    for ord in [(0, 1, 1), (1, 1, 0)]:
        preds, failed, reason = forecast_arima_b4(history, order=ord, horizons=[1, 2, 3])
        assert not failed
        assert reason is None
        assert len(preds) == 3

    # History too short
    short_history = [10.0, 20.0]
    fb_preds, fb_failed, fb_reason = forecast_arima_b4(short_history, horizons=[1, 2, 3])
    assert fb_failed is True
    assert "too short" in (fb_reason or "")
    assert fb_preds[1] == 20.0


def test_select_best_arima_order() -> None:
    """Verify ARIMA order selection evaluates validation MASE."""
    dates = pd.date_range("2010-01-01", periods=50, freq="MS").strftime("%Y-%m-%d").tolist()
    series = pd.Series(np.linspace(100.0, 200.0, 50), index=dates)

    folds = [
        OriginSplitInfo(
            origin_index=0,
            origin_month=dates[30],
            training_start_month=dates[0],
            training_end_month=dates[30],
            training_months_count=31,
            target_months={"h1": dates[31], "h2": dates[32], "h3": dates[33]},
            targets_observed={"h1": True, "h2": True, "h3": True},
        ),
        OriginSplitInfo(
            origin_index=1,
            origin_month=dates[31],
            training_start_month=dates[0],
            training_end_month=dates[31],
            training_months_count=32,
            target_months={"h1": dates[32], "h2": dates[33], "h3": dates[34]},
            targets_observed={"h1": True, "h2": True, "h3": True},
        ),
    ]

    best_order, scores = select_best_arima_order(
        series, folds, candidate_orders=((0, 1, 1), (1, 1, 0))
    )
    assert best_order in [(0, 1, 1), (1, 1, 0)]
    assert (0, 1, 1) in scores
    assert (1, 1, 0) in scores


def test_backtest_baselines_alignment() -> None:
    """Verify backtest output alignment: every fold and horizon has exactly 1 row per baseline."""
    dates = pd.date_range("2015-01-01", periods=60, freq="MS").strftime("%Y-%m-%d").tolist()
    panel_rows = [
        {"series_id": "palm_wb_myr", "month": d, "value": 2000.0 + idx * 10.0}
        for idx, d in enumerate(dates)
    ]
    panel_df = pd.DataFrame(panel_rows)

    folds = [
        OriginSplitInfo(
            origin_index=0,
            origin_month=dates[40],
            training_start_month=dates[0],
            training_end_month=dates[40],
            training_months_count=41,
            target_months={"h1": dates[41], "h2": dates[42], "h3": dates[43]},
            targets_observed={"h1": True, "h2": True, "h3": True},
        ),
        OriginSplitInfo(
            origin_index=1,
            origin_month=dates[41],
            training_start_month=dates[0],
            training_end_month=dates[41],
            training_months_count=42,
            target_months={"h1": dates[42], "h2": dates[43], "h3": dates[44]},
            targets_observed={"h1": True, "h2": True, "h3": True},
        ),
    ]

    df, order = backtest_baselines(
        panel_df,
        "palm_wb_myr",
        folds,
        split_name="validation",
        horizons=[1, 2, 3],
        arima_order=(0, 1, 1),
    )

    # 2 folds * 4 models (B1, B2, B3, B4) * 3 horizons = 24 rows
    assert len(df) == 24
    assert set(df["model"].unique()) == {"B1", "B2", "B3", "B4"}
    assert set(df["horizon"].unique()) == {1, 2, 3}
    assert order == (0, 1, 1)

    # Verify each (model, origin, horizon) combination is strictly unique
    grouped = df.groupby(["model", "origin", "horizon"]).size()
    assert (grouped == 1).all()
