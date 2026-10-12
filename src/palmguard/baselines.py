"""Baseline forecasters B1, B2, B3, and B4 (Task T11).

Defines rolling-origin forecasters per 05_FORECAST_EXPERIMENT_PLAN.md:
- B1 (Naive): y[t+h] = y[t]
- B2 (Seasonal naive): y[t+h] = y[t+h-12]
- B3 (ETS): statsmodels ETS on log price (additive error, damped trend, no seasonality).
- B4 (ARIMA): statsmodels ARIMA on log price with order in {(0,1,1), (1,1,0)}.
  Validation order selection: evaluated across validation folds, order with lower validation MASE chosen.

Fit failures in ETS and ARIMA are caught, logged per origin, and replaced by B1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

from palmguard.evaluation import calculate_mase, calculate_naive_scale
from palmguard.splits import OriginSplitInfo

logger = logging.getLogger(__name__)


@dataclass
class BaselineForecastResult:
    """Prediction output and execution metadata for a baseline model at an origin."""

    model_id: str
    origin_month: str
    predictions: dict[int, float]  # horizon -> predicted price level
    fit_failed: bool = False
    failure_reason: str | None = None
    fallback_model_id: str | None = None


def forecast_naive_b1(
    history_values: Sequence[float] | np.ndarray,
    horizons: Sequence[int] = (1, 2, 3),
) -> dict[int, float]:
    """B1: Naive forecaster: y[t+h] = y[t]."""
    hist = np.asarray(history_values, dtype=float)
    if len(hist) == 0:
        raise ValueError("Cannot forecast B1 naive with empty history")
    last_val = float(hist[-1])
    return {h: last_val for h in horizons}


def forecast_seasonal_naive_b2(
    history_values: Sequence[float] | np.ndarray,
    horizons: Sequence[int] = (1, 2, 3),
    seasonal_period: int = 12,
) -> dict[int, float]:
    """B2: Seasonal naive forecaster: y[t+h] = y[t+h-12].

    If history length is less than seasonal_period, falls back to naive B1.
    """
    hist = np.asarray(history_values, dtype=float)
    n = len(hist)
    if n == 0:
        raise ValueError("Cannot forecast B2 seasonal naive with empty history")

    preds: dict[int, float] = {}
    for h in horizons:
        idx = n + h - 1 - seasonal_period
        if idx >= 0:
            preds[h] = float(hist[idx])
        else:
            # Fallback to naive if history prior to 12 months is not available
            preds[h] = float(hist[-1])
    return preds


def forecast_ets_b3(
    history_values: Sequence[float] | np.ndarray,
    horizons: Sequence[int] = (1, 2, 3),
) -> tuple[dict[int, float], bool, str | None]:
    """B3: statsmodels ETS on log price (additive error, damped trend, no seasonality).

    Returns (predictions, fit_failed, failure_reason).
    Falls back to B1 on failure or non-positive history.
    """
    hist = np.asarray(history_values, dtype=float)
    if len(hist) < 3:
        return forecast_naive_b1(hist, horizons), True, "History too short for ETS (<3 points)"

    if np.any(hist <= 0.0):
        return forecast_naive_b1(hist, horizons), True, "Non-positive values in history"

    log_hist = np.log(hist)
    max_h = max(horizons)

    try:
        model = ETSModel(
            log_hist,
            error="add",
            trend="add",
            damped_trend=True,
            seasonal=None,
        )
        res = model.fit(disp=False)
        forecast_log = res.forecast(steps=max_h)
        # Check for NaN / Inf
        if np.any(~np.isfinite(forecast_log)):
            return forecast_naive_b1(hist, horizons), True, "ETS returned non-finite predictions"

        preds = {h: float(np.exp(forecast_log[h - 1])) for h in horizons}
        return preds, False, None
    except Exception as exc:
        logger.warning("ETS fit failed: %s; falling back to B1", exc)
        return forecast_naive_b1(hist, horizons), True, str(exc)


def forecast_arima_b4(
    history_values: Sequence[float] | np.ndarray,
    order: tuple[int, int, int] = (0, 1, 1),
    horizons: Sequence[int] = (1, 2, 3),
) -> tuple[dict[int, float], bool, str | None]:
    """B4: statsmodels ARIMA on log price with specified order.

    Returns (predictions, fit_failed, failure_reason).
    Falls back to B1 on fit failure.
    """
    hist = np.asarray(history_values, dtype=float)
    if len(hist) < 5:
        return forecast_naive_b1(hist, horizons), True, "History too short for ARIMA (<5 points)"

    if np.any(hist <= 0.0):
        return forecast_naive_b1(hist, horizons), True, "Non-positive values in history"

    log_hist = np.log(hist)
    max_h = max(horizons)

    try:
        model = ARIMA(log_hist, order=order)
        res = model.fit()
        forecast_log = res.forecast(steps=max_h)
        if np.any(~np.isfinite(forecast_log)):
            return forecast_naive_b1(hist, horizons), True, "ARIMA returned non-finite predictions"

        preds = {h: float(np.exp(forecast_log[h - 1])) for h in horizons}
        return preds, False, None
    except Exception as exc:
        logger.warning("ARIMA %s fit failed: %s; falling back to B1", order, exc)
        return forecast_naive_b1(hist, horizons), True, str(exc)


def run_baseline_fold(
    model_id: str,
    history_values: Sequence[float] | np.ndarray,
    origin_month: str,
    horizons: Sequence[int] = (1, 2, 3),
    arima_order: tuple[int, int, int] = (0, 1, 1),
) -> BaselineForecastResult:
    """Execute a single baseline model for a fold."""
    if model_id == "B1":
        preds = forecast_naive_b1(history_values, horizons=horizons)
        return BaselineForecastResult(model_id="B1", origin_month=origin_month, predictions=preds)

    if model_id == "B2":
        preds = forecast_seasonal_naive_b2(history_values, horizons=horizons)
        return BaselineForecastResult(model_id="B2", origin_month=origin_month, predictions=preds)

    if model_id == "B3":
        preds, failed, reason = forecast_ets_b3(history_values, horizons=horizons)
        return BaselineForecastResult(
            model_id="B3",
            origin_month=origin_month,
            predictions=preds,
            fit_failed=failed,
            failure_reason=reason,
            fallback_model_id="B1" if failed else None,
        )

    if model_id == "B4":
        preds, failed, reason = forecast_arima_b4(
            history_values, order=arima_order, horizons=horizons
        )
        return BaselineForecastResult(
            model_id="B4",
            origin_month=origin_month,
            predictions=preds,
            fit_failed=failed,
            failure_reason=reason,
            fallback_model_id="B1" if failed else None,
        )

    raise ValueError(f"Unknown baseline model_id: {model_id}")


def select_best_arima_order(
    series_series: pd.Series,
    folds: list[OriginSplitInfo],
    candidate_orders: Sequence[tuple[int, int, int]] = ((0, 1, 1), (1, 1, 0)),
    horizons: Sequence[int] = (1, 2, 3),
) -> tuple[tuple[int, int, int], dict[tuple[int, int, int], float]]:
    """Select the ARIMA order with lowest pooled validation MASE across validation folds."""
    order_scores: dict[tuple[int, int, int], float] = {}

    for order in candidate_orders:
        all_actuals: list[float] = []
        all_preds: list[float] = []
        scales: list[float] = []

        for fold in folds:
            hist = series_series.loc[: fold.training_end_month].values
            scale = calculate_naive_scale(hist)
            preds, _, _ = forecast_arima_b4(hist, order=order, horizons=horizons)

            for h in horizons:
                t_m = fold.target_months.get(f"h{h}")
                if t_m in series_series.index:
                    all_actuals.append(float(series_series.loc[t_m]))
                    all_preds.append(preds[h])
                    scales.append(scale)

        # Pooled MASE across all evaluated pairs
        mean_scale = float(np.mean(scales)) if scales else 1.0
        mase = calculate_mase(all_actuals, all_preds, scale=mean_scale)
        order_scores[order] = mase

    best_order = min(order_scores.keys(), key=lambda o: order_scores[o])
    return best_order, order_scores


def backtest_baselines(
    panel_df: pd.DataFrame,
    series_id: str,
    folds: list[OriginSplitInfo],
    split_name: str = "validation",
    horizons: Sequence[int] = (1, 2, 3),
    arima_order: tuple[int, int, int] | None = None,
) -> tuple[pd.DataFrame, tuple[int, int, int]]:
    """Run backtest for all baselines B1-B4 across all origins in folds.

    Returns:
    - predictions_df: DataFrame with columns:
      [series_id, model, origin, target, horizon, actual, prediction, fit_failed, fallback_model, split]
    - chosen_arima_order: (p, d, q) used for B4
    """
    s_df = (
        panel_df[panel_df["series_id"] == series_id]
        .sort_values("month")
        .set_index("month")["value"]
    )

    # Choose ARIMA order if not provided
    if arima_order is None:
        chosen_arima_order, _ = select_best_arima_order(s_df, folds, horizons=horizons)
    else:
        chosen_arima_order = arima_order

    records: list[dict[str, object]] = []
    baseline_models = ["B1", "B2", "B3", "B4"]

    for fold in folds:
        hist = s_df.loc[: fold.training_end_month].values

        for m_id in baseline_models:
            res = run_baseline_fold(
                m_id,
                hist,
                origin_month=fold.origin_month,
                horizons=horizons,
                arima_order=chosen_arima_order,
            )

            for h in horizons:
                t_m = fold.target_months.get(f"h{h}")
                act_val = float(s_df.loc[t_m]) if (t_m and t_m in s_df.index) else None

                records.append(
                    {
                        "series_id": series_id,
                        "model": m_id,
                        "origin": fold.origin_month,
                        "target": t_m,
                        "horizon": h,
                        "actual": act_val,
                        "prediction": res.predictions[h],
                        "fit_failed": res.fit_failed,
                        "fallback_model": res.fallback_model_id,
                        "split": split_name,
                    }
                )

    df_out = pd.DataFrame(records)
    return df_out, chosen_arima_order
