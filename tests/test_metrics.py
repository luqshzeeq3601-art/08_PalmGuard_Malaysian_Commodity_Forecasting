"""Hand-calculated fixtures and unit tests for evaluation metrics (Task T10)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from palmguard.evaluation import (
    calculate_bias,
    calculate_mae,
    calculate_mase,
    calculate_naive_scale,
    calculate_pinball_loss,
    calculate_rmse,
    calculate_wape,
    calculate_wilson_interval,
    evaluate_coverage,
    evaluate_interval_width,
    evaluate_point_forecasts,
    evaluate_prediction_intervals,
)


def test_hand_calculated_point_metrics() -> None:
    """Reconcile point metrics against analytical hand calculation."""
    # Actuals: [100.0, 110.0, 120.0, 130.0]
    # Forecasts: [105.0, 108.0, 124.0, 128.0]
    y_true = [100.0, 110.0, 120.0, 130.0]
    y_pred = [105.0, 108.0, 124.0, 128.0]

    # Errors: y_pred - y_true:
    # [5.0, -2.0, 4.0, -2.0]
    # Absolute errors: [5.0, 2.0, 4.0, 2.0] -> sum = 13.0, mean MAE = 13.0 / 4 = 3.25
    # Squared errors: [25.0, 4.0, 16.0, 4.0] -> sum = 49.0, mean MSE = 12.25, RMSE = 3.5
    # Bias (mean signed error): (5 - 2 + 4 - 2) / 4 = 5.0 / 4 = 1.25
    # Sum actuals = 100 + 110 + 120 + 130 = 460.0
    # WAPE = 13.0 / 460.0 = 0.02826086956521739

    assert calculate_mae(y_true, y_pred) == pytest.approx(3.25)
    assert calculate_rmse(y_true, y_pred) == pytest.approx(3.5)
    assert calculate_bias(y_true, y_pred) == pytest.approx(1.25)
    assert calculate_wape(y_true, y_pred) == pytest.approx(13.0 / 460.0)


def test_naive_scale_and_mase_hand_calculated() -> None:
    """Verify naive scale and MASE match hand calculation and B1 definition."""
    # Training window: [100.0, 102.0, 101.0, 105.0, 110.0]
    # Consecutive diffs: |102-100|=2, |101-102|=1, |105-101|=4, |110-105|=5
    # Sum diffs = 2 + 1 + 4 + 5 = 12.0
    # Mean diff (naive scale) = 12.0 / 4 = 3.0
    train_history = [100.0, 102.0, 101.0, 105.0, 110.0]
    scale = calculate_naive_scale(train_history)
    assert scale == pytest.approx(3.0)

    # If test MAE = 3.25, MASE = 3.25 / 3.0 = 1.08333333333
    y_true = [100.0, 110.0, 120.0, 130.0]
    y_pred = [105.0, 108.0, 124.0, 128.0]
    assert calculate_mase(y_true, y_pred, scale=scale) == pytest.approx(3.25 / 3.0)

    # By construction, naive forecast (y_pred = train_history[:-1]) on training window:
    # in-sample MAE of naive is exactly 3.0, so in-sample MASE is 1.0
    in_sample_naive_mase = calculate_mase(train_history[1:], train_history[:-1], scale=scale)
    assert in_sample_naive_mase == pytest.approx(1.0)


def test_zero_denominator_edge_cases() -> None:
    """Verify zero-denominator guard rules across all metrics."""
    # Empty inputs
    assert calculate_mae([], []) == 0.0
    assert calculate_rmse([], []) == 0.0
    assert calculate_bias([], []) == 0.0
    assert calculate_wape([], []) == 0.0
    assert calculate_mase([], [], scale=1.0) == 0.0
    assert calculate_naive_scale([]) == 0.0
    assert calculate_naive_scale([100.0]) == 0.0

    # Constant training history -> scale is 0.0
    const_train = [100.0, 100.0, 100.0]
    zero_scale = calculate_naive_scale(const_train)
    assert zero_scale == 0.0

    # MASE with zero scale:
    # 1. Perfect forecast (MAE == 0) -> returns 0.0
    assert calculate_mase([100.0], [100.0], scale=zero_scale) == 0.0
    # 2. Non-zero error with zero scale -> returns inf
    assert math.isinf(calculate_mase([100.0], [105.0], scale=zero_scale))

    # WAPE with all actuals = 0.0
    assert calculate_wape([0.0, 0.0], [0.0, 0.0]) == 0.0
    assert math.isnan(calculate_wape([0.0, 0.0], [1.0, 2.0]))

    # Wilson interval with total = 0
    assert calculate_wilson_interval(0, 0) == (0.0, 0.0)


def test_hand_calculated_pinball_loss() -> None:
    """Verify pinball loss matches exact analytical quantile loss."""
    # Let y = 100.0, tau = 0.90
    # Case 1: Under-forecast (q = 90.0, y > q):
    # error = 100 - 90 = 10.0
    # L_0.90 = 0.90 * 10.0 = 9.0
    assert calculate_pinball_loss([100.0], [90.0], quantile=0.90) == pytest.approx(9.0)

    # Case 2: Over-forecast (q = 110.0, y < q):
    # error = 100 - 110 = -10.0
    # L_0.90 = (0.90 - 1.0) * (-10.0) = -0.10 * -10.0 = 1.0
    assert calculate_pinball_loss([100.0], [110.0], quantile=0.90) == pytest.approx(1.0)

    # Case 3: tau = 0.10, under-forecast (q = 90.0):
    # error = 10.0 -> L_0.10 = 0.10 * 10.0 = 1.0
    assert calculate_pinball_loss([100.0], [90.0], quantile=0.10) == pytest.approx(1.0)

    # Case 4: tau = 0.10, over-forecast (q = 110.0):
    # error = -10.0 -> L_0.10 = (0.10 - 1.0) * (-10.0) = 9.0
    assert calculate_pinball_loss([100.0], [110.0], quantile=0.10) == pytest.approx(9.0)

    # Case 5: tau = 0.50 (median / MAE / 2):
    # For error 10.0, loss is 0.50 * 10 = 5.0 = |error| / 2
    assert calculate_pinball_loss([100.0], [90.0], quantile=0.50) == pytest.approx(5.0)


def test_wilson_confidence_interval_bounds() -> None:
    """Verify Wilson score interval properties: within [0, 1], tight around p_hat."""
    # 20 covered out of 24
    lower, upper = calculate_wilson_interval(20, 24, confidence=0.95)
    p_hat = 20 / 24

    assert 0.0 <= lower <= p_hat <= upper <= 1.0
    # Hand calculation verification using scipy standard normal quantile
    # z = 1.95996 -> center = 0.78734, margin = 0.14587
    assert lower == pytest.approx(0.6415, abs=1e-3)
    assert upper == pytest.approx(0.9332, abs=1e-3)

    # Boundary cases: 0 / 24 and 24 / 24
    l_zero, u_zero = calculate_wilson_interval(0, 24, confidence=0.95)
    assert l_zero == 0.0
    assert 0.0 < u_zero < 0.20

    l_full, u_full = calculate_wilson_interval(24, 24, confidence=0.95)
    assert 0.80 < l_full < 1.0
    assert u_full == 1.0


def test_interval_evaluation_and_width() -> None:
    """Verify interval coverage, mean width, and width percentage."""
    y_true = [100.0, 105.0, 110.0, 120.0, 150.0]
    # Lower bounds: [90.0, 100.0, 108.0, 115.0, 160.0] -> 5th misses (150 < 160)
    # Upper bounds: [110.0, 110.0, 112.0, 125.0, 170.0]
    lower = [90.0, 100.0, 108.0, 115.0, 160.0]
    upper = [110.0, 110.0, 112.0, 125.0, 170.0]

    # Coverage: 4 covered out of 5 -> 0.80
    cov = evaluate_coverage(y_true, lower, upper, nominal_level=0.80)
    assert cov.covered_count == 4
    assert cov.total_eval_count == 5
    assert cov.coverage_rate == pytest.approx(0.80)

    # Widths: [20.0, 10.0, 4.0, 10.0, 10.0] -> sum = 54.0, mean = 10.8
    # Mean actual: (100 + 105 + 110 + 120 + 150) / 5 = 585 / 5 = 117.0
    # Mean width pct: (10.8 / 117.0) * 100 = 9.230769...
    w, w_pct = evaluate_interval_width(lower, upper, y_true=y_true)
    assert w == pytest.approx(10.8)
    assert w_pct == pytest.approx(10.8 / 117.0 * 100.0)

    # Full interval metrics container
    metrics = evaluate_prediction_intervals(y_true, lower, upper, nominal_level=0.80)
    assert metrics.coverage.coverage_rate == pytest.approx(0.80)
    assert metrics.mean_width == pytest.approx(10.8)
    assert metrics.pinball_lower > 0.0
    assert metrics.pinball_upper > 0.0


def test_point_metrics_container() -> None:
    """Verify PointMetrics evaluation helper outputs valid typed dictionary."""
    y_true = np.array([1000.0, 2000.0])
    y_pred = np.array([1010.0, 1990.0])
    scale = 50.0

    pm = evaluate_point_forecasts(y_true, y_pred, scale=scale)
    assert pm.eval_count == 2
    assert pm.mae == pytest.approx(10.0)
    assert pm.rmse == pytest.approx(10.0)
    assert pm.mase == pytest.approx(10.0 / 50.0)
    assert pm.wape == pytest.approx(20.0 / 3000.0)
    assert pm.bias == pytest.approx(0.0)
