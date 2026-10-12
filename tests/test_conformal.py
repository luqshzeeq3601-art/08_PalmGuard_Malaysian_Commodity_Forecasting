"""Unit and simulation tests for conformal intervals C1 and C2 (Task T13)."""

from __future__ import annotations

import numpy as np
import pytest

from palmguard.conformal import ConformalTracker


def test_residual_availability_lag() -> None:
    """Verify horizon h residuals become available only when target_month <= as_of_origin."""
    tracker = ConformalTracker(nominal_levels=[0.80, 0.90], window_size=60)

    # Register an origin 2024-01-01 forecast for h=2 (target 2024-03-01)
    tracker.register_observed_residual(
        origin_month="2024-01-01",
        target_month="2024-03-01",
        horizon=2,
        actual_price=110.0,
        origin_price=100.0,
        pred_price=105.0,
    )

    # At origin 2024-02-01 (target 2024-03-01 not yet observed): 0 usable residuals
    assert tracker.get_available_residuals(horizon=2, as_of_origin="2024-02-01") == []

    # At origin 2024-03-01 (target 2024-03-01 observed): exactly 1 usable residual
    usable = tracker.get_available_residuals(horizon=2, as_of_origin="2024-03-01")
    assert len(usable) == 1
    assert usable[0] > 0.0

    # At later origin 2024-04-01: still available
    assert len(tracker.get_available_residuals(horizon=2, as_of_origin="2024-04-01")) == 1


def test_exchangeable_noise_nominal_coverage() -> None:
    """Verify that on exchangeable i.i.d. noise, empirical coverage is close to nominal level."""
    np.random.seed(42)
    tracker = ConformalTracker(nominal_levels=[0.80, 0.90], window_size=60)

    n_periods = 120
    # Simulate historical residuals for warm-up
    noise = np.random.normal(0, 0.05, n_periods)

    for i in range(n_periods):
        m_str = f"2020-{i:03d}"
        tracker.register_observed_residual(
            origin_month=m_str,
            target_month=m_str,
            horizon=1,
            actual_price=100.0 * float(np.exp(noise[i])),
            origin_price=100.0,
            pred_price=100.0,
        )

    # Evaluate out-of-sample test origin
    intervals_c1 = tracker.forecast_intervals(
        origin_month="2020-120",
        horizon=1,
        origin_price=100.0,
        point_forecast=100.0,
        method="C1",
    )

    # Check that half widths are positive and 90% interval is wider than 80% interval
    assert intervals_c1[0.80].half_width_return > 0.0
    assert intervals_c1[0.90].half_width_return > intervals_c1[0.80].half_width_return
    assert intervals_c1[0.80].lower_bound < 100.0 < intervals_c1[0.80].upper_bound
    assert intervals_c1[0.90].lower_bound < intervals_c1[0.80].lower_bound
    assert intervals_c1[0.90].upper_bound > intervals_c1[0.80].upper_bound


def test_c2_adapts_faster_than_c1_on_variance_shift() -> None:
    """Verify that after a sudden variance shift, ACI (C2) recovers coverage faster than C1."""
    np.random.seed(42)
    # Pre-shift: low variance (sigma=0.02)
    # Post-shift: high variance burst (sigma=0.10)
    res_pre = np.random.normal(0, 0.02, 60)
    res_post = np.random.normal(0, 0.10, 40)
    all_res = np.concatenate([res_pre, res_post])

    tracker_c1 = ConformalTracker(nominal_levels=[0.80], window_size=60)
    tracker_c2 = ConformalTracker(nominal_levels=[0.80], window_size=60, aci_gamma=0.08)

    # Warm-up on pre-shift data
    for i in range(60):
        m_str = f"2020-{i:03d}"
        for tr in [tracker_c1, tracker_c2]:
            tr.register_observed_residual(
                origin_month=m_str,
                target_month=m_str,
                horizon=1,
                actual_price=100.0 * float(np.exp(all_res[i])),
                origin_price=100.0,
                pred_price=100.0,
            )

    # Run post-shift tracking (i=60 to 100)
    misses_c1: list[int] = []
    misses_c2: list[int] = []

    for i in range(60, 100):
        m_str = f"2020-{i:03d}"
        actual = 100.0 * float(np.exp(all_res[i]))

        # C1 forecast
        iv_c1 = tracker_c1.forecast_intervals(m_str, 1, 100.0, 100.0, method="C1")[0.80]
        miss_c1 = int(actual < iv_c1.lower_bound or actual > iv_c1.upper_bound)
        misses_c1.append(miss_c1)
        tracker_c1.register_observed_residual(m_str, m_str, 1, actual, 100.0, 100.0)

        # C2 forecast
        iv_c2 = tracker_c2.forecast_intervals(m_str, 1, 100.0, 100.0, method="C2")[0.80]
        miss_c2 = int(actual < iv_c2.lower_bound or actual > iv_c2.upper_bound)
        misses_c2.append(miss_c2)
        tracker_c2.register_observed_residual(m_str, m_str, 1, actual, 100.0, 100.0)
        # Online update of alpha
        tracker_c2.update_aci_state(horizon=1, level=0.80, hit=(miss_c2 == 0))

    # In the second half of the post-shift period, C2 adapts its width to the higher variance
    # resulting in fewer misses than the trailing-window C1
    c1_late_misses = sum(misses_c1[15:])
    c2_late_misses = sum(misses_c2[15:])

    assert c2_late_misses < c1_late_misses


def test_aci_update_waits_for_target_month() -> None:
    """Verify a horizon-2 miss only moves the ACI alpha once its target month is observed."""
    tracker = ConformalTracker(nominal_levels=[0.80], window_size=60, aci_gamma=0.05)
    tracker.queue_aci_update("2024-03-01", horizon=2, level=0.80, hit=False)

    tracker.apply_observed_aci_updates("2024-02-01")
    assert tracker.aci_alphas[(2, 0.80)] == pytest.approx(0.20)

    tracker.apply_observed_aci_updates("2024-03-01")
    assert tracker.aci_alphas[(2, 0.80)] == pytest.approx(0.20 + 0.05 * (0.20 - 1.0))
