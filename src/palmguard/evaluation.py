"""Forecast evaluation metrics and statistical scoring routines (Task T10).

Metrics defined per 05_FORECAST_EXPERIMENT_PLAN.md:
- MASE: Mean Absolute Scaled Error (scaled by training window 1-step naive MAE).
- WAPE: Weighted Absolute Percentage Error (sum(abs(y - yhat)) / sum(y)).
- Pinball loss: Quantile loss at alphas {0.05, 0.10, 0.50, 0.90, 0.95}.
- Coverage: Empirical interval coverage share with Wilson score binomial interval.
- Mean interval width: Level units and percentage of price level.
- Bias: Mean signed error (mean(yhat - y)).
- Zero-denominator guard rules: Returns 0.0 or nan according to defined edge conditions.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict
from scipy import stats


class CoverageResult(BaseModel):
    """Interval coverage summary with binomial confidence interval."""

    model_config = ConfigDict(extra="forbid")

    nominal_level: float
    total_eval_count: int
    covered_count: int
    coverage_rate: float
    ci_lower: float
    ci_upper: float
    ci_confidence: float = 0.95


class PointMetrics(BaseModel):
    """Summary of point forecast error metrics."""

    model_config = ConfigDict(extra="forbid")

    eval_count: int
    mae: float
    rmse: float
    mase: float
    wape: float
    bias: float


class IntervalMetrics(BaseModel):
    """Summary of prediction interval evaluation."""

    model_config = ConfigDict(extra="forbid")

    eval_count: int
    nominal_level: float
    coverage: CoverageResult
    mean_width: float
    mean_width_pct: float
    pinball_lower: float
    pinball_upper: float


def calculate_mae(
    y_true: Sequence[float] | np.ndarray,
    y_pred: Sequence[float] | np.ndarray,
) -> float:
    """Mean Absolute Error: mean(|y - y_hat|)."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    if len(yt) == 0:
        return 0.0
    if len(yt) != len(yp):
        raise ValueError(f"Length mismatch: {len(yt)} != {len(yp)}")
    return float(np.mean(np.abs(yt - yp)))


def calculate_rmse(
    y_true: Sequence[float] | np.ndarray,
    y_pred: Sequence[float] | np.ndarray,
) -> float:
    """Root Mean Squared Error: sqrt(mean((y - y_hat)^2))."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    if len(yt) == 0:
        return 0.0
    if len(yt) != len(yp):
        raise ValueError(f"Length mismatch: {len(yt)} != {len(yp)}")
    return float(np.sqrt(np.mean((yt - yp) ** 2)))


def calculate_bias(
    y_true: Sequence[float] | np.ndarray,
    y_pred: Sequence[float] | np.ndarray,
) -> float:
    """Mean Signed Error: mean(y_hat - y). Positive indicates over-forecasting."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    if len(yt) == 0:
        return 0.0
    if len(yt) != len(yp):
        raise ValueError(f"Length mismatch: {len(yt)} != {len(yp)}")
    return float(np.mean(yp - yt))


def calculate_wape(
    y_true: Sequence[float] | np.ndarray,
    y_pred: Sequence[float] | np.ndarray,
) -> float:
    """Weighted Absolute Percentage Error: sum(|y - y_hat|) / sum(|y|).

    Zero-denominator rule: If sum(|y|) == 0:
    - If sum(|y - y_hat|) == 0, returns 0.0 (exact zero match).
    - Otherwise returns float('nan').
    """
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    if len(yt) == 0:
        return 0.0
    if len(yt) != len(yp):
        raise ValueError(f"Length mismatch: {len(yt)} != {len(yp)}")

    abs_err_sum = float(np.sum(np.abs(yt - yp)))
    denom = float(np.sum(np.abs(yt)))

    if denom == 0.0:
        return 0.0 if abs_err_sum == 0.0 else float("nan")

    return abs_err_sum / denom


def calculate_naive_scale(
    y_train_history: Sequence[float] | np.ndarray,
) -> float:
    """Calculate in-sample mean absolute one-step naive error on training history:

    scale = mean(|y_t - y_{t-1}|) for t=1..T-1.
    Zero-denominator rule: Returns 0.0 if history has < 2 points or is strictly constant.
    """
    history = np.asarray(y_train_history, dtype=float)
    if len(history) < 2:
        return 0.0
    diffs = np.abs(np.diff(history))
    scale = float(np.mean(diffs))
    return scale


def calculate_mase(
    y_true: Sequence[float] | np.ndarray,
    y_pred: Sequence[float] | np.ndarray,
    scale: float,
) -> float:
    """Mean Absolute Scaled Error: MAE / scale.

    scale is the in-sample mean absolute error of 1-step naive on the training window.
    Zero-denominator rule:
    - If MAE == 0, returns 0.0.
    - If scale <= 0 and MAE > 0, returns float('inf').
    """
    mae = calculate_mae(y_true, y_pred)
    if mae == 0.0:
        return 0.0
    if scale <= 0.0 or math.isnan(scale):
        return float("inf")
    return mae / scale


def calculate_pinball_loss(
    y_true: Sequence[float] | np.ndarray,
    y_pred_quantile: Sequence[float] | np.ndarray,
    quantile: float,
) -> float:
    """Pinball (quantile) loss for quantile tau in (0, 1):

    L_tau(y, q) = max(tau * (y - q), (tau - 1) * (y - q))
    = (y - q) * (tau - I(y < q))
    """
    if not (0.0 < quantile < 1.0):
        raise ValueError(f"Quantile must be in (0, 1), got {quantile}")

    yt = np.asarray(y_true, dtype=float)
    yq = np.asarray(y_pred_quantile, dtype=float)
    if len(yt) == 0:
        return 0.0
    if len(yt) != len(yq):
        raise ValueError(f"Length mismatch: {len(yt)} != {len(yq)}")

    errors = yt - yq
    loss = np.maximum(quantile * errors, (quantile - 1.0) * errors)
    return float(np.mean(loss))


def calculate_wilson_interval(
    successes: int,
    total: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Calculate the Wilson score confidence interval for a binomial proportion.

    Formula:
    (p + z^2/(2n) +/- z * sqrt(p(1-p)/n + z^2/(4n^2))) / (1 + z^2/n)
    bounded in [0.0, 1.0].
    """
    if total <= 0:
        return (0.0, 0.0)
    if not (0 <= successes <= total):
        raise ValueError(f"Invalid successes {successes} for total {total}")
    if not (0.0 < confidence < 1.0):
        raise ValueError(f"Confidence must be in (0, 1), got {confidence}")

    p_hat = successes / total
    z = float(stats.norm.ppf((1.0 + confidence) / 2.0))
    denom = 1.0 + (z**2) / total
    center = (p_hat + (z**2) / (2.0 * total)) / denom
    margin = (z / denom) * math.sqrt((p_hat * (1.0 - p_hat) / total) + (z**2) / (4.0 * (total**2)))

    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)

    # Clean floating-point artifacts at boundaries
    if successes == 0:
        lower = 0.0
    if successes == total:
        upper = 1.0

    return (float(lower), float(upper))


def evaluate_coverage(
    y_true: Sequence[float] | np.ndarray,
    lower_bound: Sequence[float] | np.ndarray,
    upper_bound: Sequence[float] | np.ndarray,
    nominal_level: float,
    confidence: float = 0.95,
) -> CoverageResult:
    """Evaluate empirical coverage share and binomial Wilson confidence interval."""
    yt = np.asarray(y_true, dtype=float)
    lb = np.asarray(lower_bound, dtype=float)
    ub = np.asarray(upper_bound, dtype=float)
    if len(yt) != len(lb) or len(yt) != len(ub):
        raise ValueError("Length mismatch between actuals and bounds")

    total = len(yt)
    if total == 0:
        return CoverageResult(
            nominal_level=nominal_level,
            total_eval_count=0,
            covered_count=0,
            coverage_rate=0.0,
            ci_lower=0.0,
            ci_upper=0.0,
            ci_confidence=confidence,
        )

    # Actual is covered if lb <= y <= ub
    covered = (yt >= lb) & (yt <= ub)
    successes = int(np.sum(covered))
    rate = successes / total
    ci_l, ci_u = calculate_wilson_interval(successes, total, confidence=confidence)

    return CoverageResult(
        nominal_level=nominal_level,
        total_eval_count=total,
        covered_count=successes,
        coverage_rate=rate,
        ci_lower=ci_l,
        ci_upper=ci_u,
        ci_confidence=confidence,
    )


def evaluate_interval_width(
    lower_bound: Sequence[float] | np.ndarray,
    upper_bound: Sequence[float] | np.ndarray,
    y_true: Sequence[float] | np.ndarray | None = None,
) -> tuple[float, float]:
    """Calculate mean interval width in level units and as a percentage of actual level:

    Returns (mean_width, mean_width_pct).
    Zero-denominator rule for percentage: if mean(|y|) == 0, returns nan.
    """
    lb = np.asarray(lower_bound, dtype=float)
    ub = np.asarray(upper_bound, dtype=float)
    if len(lb) == 0:
        return 0.0, 0.0
    if len(lb) != len(ub):
        raise ValueError(f"Length mismatch: {len(lb)} != {len(ub)}")

    widths = ub - lb
    mean_width = float(np.mean(widths))

    if y_true is None:
        return mean_width, 0.0

    yt = np.asarray(y_true, dtype=float)
    mean_actual = float(np.mean(np.abs(yt)))
    if mean_actual == 0.0:
        width_pct = float("nan")
    else:
        width_pct = (mean_width / mean_actual) * 100.0

    return mean_width, width_pct


def evaluate_prediction_intervals(
    y_true: Sequence[float] | np.ndarray,
    lower_bound: Sequence[float] | np.ndarray,
    upper_bound: Sequence[float] | np.ndarray,
    nominal_level: float,
    confidence: float = 0.95,
) -> IntervalMetrics:
    """Full prediction interval evaluation at a declared nominal level (e.g. 0.80 or 0.90).

    Computes:
    - Coverage result with Wilson interval.
    - Mean interval width (absolute and percentage).
    - Pinball loss at the lower alpha quantile and upper (1 - alpha) quantile.
    """
    yt = np.asarray(y_true, dtype=float)
    lb = np.asarray(lower_bound, dtype=float)
    ub = np.asarray(upper_bound, dtype=float)

    total = len(yt)
    coverage = evaluate_coverage(yt, lb, ub, nominal_level=nominal_level, confidence=confidence)
    mean_w, mean_w_pct = evaluate_interval_width(lb, ub, y_true=yt)

    alpha_lower = (1.0 - nominal_level) / 2.0
    alpha_upper = 1.0 - alpha_lower

    pinball_l = calculate_pinball_loss(yt, lb, quantile=alpha_lower) if total > 0 else 0.0
    pinball_u = calculate_pinball_loss(yt, ub, quantile=alpha_upper) if total > 0 else 0.0

    return IntervalMetrics(
        eval_count=total,
        nominal_level=nominal_level,
        coverage=coverage,
        mean_width=mean_w,
        mean_width_pct=mean_w_pct,
        pinball_lower=pinball_l,
        pinball_upper=pinball_u,
    )


def evaluate_point_forecasts(
    y_true: Sequence[float] | np.ndarray,
    y_pred: Sequence[float] | np.ndarray,
    scale: float,
) -> PointMetrics:
    """Compute comprehensive point forecast metrics: MAE, RMSE, MASE, WAPE, Bias."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    return PointMetrics(
        eval_count=len(yt),
        mae=calculate_mae(yt, yp),
        rmse=calculate_rmse(yt, yp),
        mase=calculate_mase(yt, yp, scale=scale),
        wape=calculate_wape(yt, yp),
        bias=calculate_bias(yt, yp),
    )
