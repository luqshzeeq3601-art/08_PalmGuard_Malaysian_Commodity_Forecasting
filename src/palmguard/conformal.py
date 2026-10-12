"""Conformal prediction intervals C1 and C2, and MAPIE spike evaluation (Task T13).

Methods per 05_FORECAST_EXPERIMENT_PLAN.md:
- C1 Rolling split conformal:
  At origin t, half-width is the empirical quantile of absolute out-of-sample residuals
  (log-return scale) from earlier origins observed by t, using trailing window of 60.
- C2 Adaptive conformal inference (ACI, Gibbs & Candes):
  Same residual scores, but online miscoverage level is updated:
  alpha_{t+1} = alpha_t + gamma * (alpha_target - miss_t)
  with gamma declared in config (default 0.05).
- Residual availability constraint:
  Residuals used at origin t come only from forecasts whose targets were observed by t.
  A horizon-h residual becomes available h months after its origin.
- MAPIE spike decision:
  MAPIE is not installed in the locked dependencies and external packages are excluded.
  Decision D06 is recorded: drop MAPIE, keep clean stdlib/scipy implementations of C1 and C2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict


class ConformalInterval(BaseModel):
    """Conformal prediction interval at a single horizon and nominal level."""

    model_config = ConfigDict(extra="forbid")

    horizon: int
    nominal_level: float
    point_forecast: float
    lower_bound: float
    upper_bound: float
    half_width_return: float
    effective_alpha: float | None = None


@dataclass
class ResidualRecord:
    """Historical forecast residual observed for a horizon."""

    origin_month: str
    target_month: str
    horizon: int
    actual_return: float
    pred_return: float
    abs_residual: float


class ConformalTracker:
    """Tracks historical residuals and computes C1 / C2 intervals per horizon."""

    def __init__(
        self,
        nominal_levels: Sequence[float] = (0.80, 0.90),
        window_size: int = 60,
        aci_gamma: float = 0.05,
    ) -> None:
        self.nominal_levels = list(nominal_levels)
        self.window_size = window_size
        self.aci_gamma = aci_gamma

        # Map of horizon -> list of ResidualRecord
        self.residual_pool: dict[int, list[ResidualRecord]] = {1: [], 2: [], 3: []}

        # Map of (horizon, level) -> current alpha for ACI
        self.aci_alphas: dict[tuple[int, float], float] = {
            (h, lvl): float(1.0 - lvl) for h in [1, 2, 3] for lvl in self.nominal_levels
        }

        # ACI outcomes waiting for their target month: (target_month, horizon, level, hit)
        self._pending_aci: list[tuple[str, int, float, bool]] = []

    def register_observed_residual(
        self,
        origin_month: str,
        target_month: str,
        horizon: int,
        actual_price: float,
        origin_price: float,
        pred_price: float,
    ) -> None:
        """Register a realized forecast and residual once target_month is observed.

        Residual is computed on the log return scale:
        actual_return = ln(actual / origin)
        pred_return = ln(pred / origin)
        abs_residual = |actual_return - pred_return|
        """
        if actual_price <= 0.0 or origin_price <= 0.0 or pred_price <= 0.0:
            return

        act_r = float(np.log(actual_price / origin_price))
        pred_r = float(np.log(pred_price / origin_price))
        abs_res = abs(act_r - pred_r)

        rec = ResidualRecord(
            origin_month=origin_month,
            target_month=target_month,
            horizon=horizon,
            actual_return=act_r,
            pred_return=pred_r,
            abs_residual=abs_res,
        )
        self.residual_pool.setdefault(horizon, []).append(rec)

    def update_aci_state(
        self,
        horizon: int,
        level: float,
        hit: bool,
    ) -> float:
        """Update ACI alpha: alpha_{t+1} = alpha_t + gamma * (alpha_target - miss_t)."""
        alpha_target = 1.0 - level
        current_alpha = self.aci_alphas.get((horizon, level), alpha_target)
        miss = 0.0 if hit else 1.0

        new_alpha = current_alpha + self.aci_gamma * (alpha_target - miss)
        # Clamp alpha to valid quantile range [0.01, 0.99]
        new_alpha = float(np.clip(new_alpha, 0.01, 0.99))
        self.aci_alphas[(horizon, level)] = new_alpha
        return new_alpha

    def queue_aci_update(self, target_month: str, horizon: int, level: float, hit: bool) -> None:
        """Hold an ACI outcome until its target month is observed."""
        self._pending_aci.append((target_month, horizon, level, hit))

    def apply_observed_aci_updates(self, as_of_origin: str) -> None:
        """Apply queued ACI outcomes whose target month was observed by as_of_origin.

        Same availability rule as residuals: a horizon-h hit or miss is only known
        h months after its origin, so alpha must not move before then.
        """
        due = sorted(p for p in self._pending_aci if p[0] <= as_of_origin)
        self._pending_aci = [p for p in self._pending_aci if p[0] > as_of_origin]
        for _, horizon, level, hit in due:
            self.update_aci_state(horizon, level, hit)

    def get_available_residuals(
        self,
        horizon: int,
        as_of_origin: str,
    ) -> list[float]:
        """Return residuals available at as_of_origin (where target_month <= as_of_origin).

        Enforces publication timing / observation lag: a horizon h residual
        is available at origin t only if its target month was already observed by t.
        """
        records = self.residual_pool.get(horizon, [])
        # Only include records where target_month <= as_of_origin
        usable = [r.abs_residual for r in records if r.target_month <= as_of_origin]
        if self.window_size > 0:
            usable = usable[-self.window_size :]
        return usable

    def compute_conformal_half_width(
        self,
        horizon: int,
        as_of_origin: str,
        effective_alpha: float,
        default_half_width: float = 0.15,
    ) -> float:
        """Compute empirical quantile of absolute residuals at 1 - effective_alpha.

        Conformal quantile formula with finite-sample correction:
        q_level = ceil((n + 1) * (1 - alpha)) / n
        """
        residuals = self.get_available_residuals(horizon, as_of_origin)
        n = len(residuals)
        if n < 5:
            # Fallback default half-width (in log-return scale) when history is scarce
            return default_half_width

        q_target = 1.0 - effective_alpha
        # Conformal finite-sample adjusted level
        corrected_q = min(1.0, math.ceil((n + 1) * q_target) / n)
        hw = float(np.quantile(residuals, corrected_q, method="higher"))
        return max(1e-4, hw)

    def forecast_intervals(
        self,
        origin_month: str,
        horizon: int,
        origin_price: float,
        point_forecast: float,
        method: str = "C1",  # 'C1' or 'C2'
    ) -> dict[float, ConformalInterval]:
        """Compute conformal intervals at all configured nominal levels for a horizon.

        Bounds are constructed symmetrically on the log-return scale and transformed
        to the price scale:
        lower = point_forecast * exp(-half_width)
        upper = point_forecast * exp(+half_width)
        """
        results: dict[float, ConformalInterval] = {}

        for level in self.nominal_levels:
            if method == "C1":
                effective_alpha = 1.0 - level
            elif method == "C2":
                effective_alpha = self.aci_alphas.get((horizon, level), 1.0 - level)
            else:
                raise ValueError(f"Unknown conformal method: {method}")

            hw = self.compute_conformal_half_width(
                horizon=horizon,
                as_of_origin=origin_month,
                effective_alpha=effective_alpha,
            )

            # Price scale bounds
            lb = point_forecast * float(np.exp(-hw))
            ub = point_forecast * float(np.exp(hw))

            results[level] = ConformalInterval(
                horizon=horizon,
                nominal_level=level,
                point_forecast=point_forecast,
                lower_bound=lb,
                upper_bound=ub,
                half_width_return=hw,
                effective_alpha=effective_alpha,
            )

        return results


def replay_conformal_intervals(
    tracker: ConformalTracker,
    preds: pd.DataFrame,
    origin_prices: Mapping[str, float],
    method: str,
) -> pd.DataFrame:
    """Replay one model's forecasts through the tracker in origin order.

    preds needs columns origin, target, horizon, actual, prediction. Each interval uses
    only residuals and ACI outcomes whose target month was observed by its origin.
    Rows without an actual are skipped. Returns one row per forecast and nominal level
    and leaves the tracker warmed for the next origin.
    """
    rows: list[dict[str, object]] = []
    ordered = preds.sort_values(["origin", "horizon"])

    for origin, group in ordered.groupby("origin", sort=True):
        origin = str(origin)
        origin_price = float(origin_prices[origin])
        if method == "C2":
            tracker.apply_observed_aci_updates(origin)

        for r in group.itertuples(index=False):
            if pd.isna(r.actual):
                continue
            horizon = int(r.horizon)
            actual = float(r.actual)
            pred = float(r.prediction)
            target = str(r.target)

            intervals = tracker.forecast_intervals(origin, horizon, origin_price, pred, method)
            for level, iv in intervals.items():
                hit = bool(iv.lower_bound <= actual <= iv.upper_bound)
                rows.append(
                    {
                        "origin": origin,
                        "target": target,
                        "horizon": horizon,
                        "nominal_level": level,
                        "actual": actual,
                        "prediction": pred,
                        "lower_bound": iv.lower_bound,
                        "upper_bound": iv.upper_bound,
                        "hit": hit,
                    }
                )
                if method == "C2":
                    tracker.queue_aci_update(target, horizon, level, hit)

            tracker.register_observed_residual(origin, target, horizon, actual, origin_price, pred)

    return pd.DataFrame(
        rows,
        columns=[
            "origin",
            "target",
            "horizon",
            "nominal_level",
            "actual",
            "prediction",
            "lower_bound",
            "upper_bound",
            "hit",
        ],
    )
