"""Reporting, metrics compilation, and champion selection routines (Task T14).

Implements:
- Selection rules from 05_FORECAST_EXPERIMENT_PLAN.md section 8:
  1. Lowest pooled validation MASE.
  2. If within 2% relative MASE tie threshold, the simpler candidate wins
     (Order: B1, B2, B3, B4, M1, M2).
  3. Interval method (C1 vs C2) selected by lowest mean absolute coverage error
     (|empirical coverage - nominal| averaged over horizons and levels) first,
     mean width second.
- Generation of reports/validation_metrics.csv and reports/validation_coverage.csv.
- Construction and export of artifacts/champion/selection_record.json,
  metadata.json, and conformal_state.json prior to holdout scoring.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from palmguard.config import ProjectConfig, load_config
from palmguard.conformal import ConformalTracker, replay_conformal_intervals
from palmguard.evaluation import (
    calculate_bias,
    calculate_mae,
    calculate_mase,
    calculate_naive_scale,
    calculate_rmse,
    calculate_wape,
    evaluate_prediction_intervals,
)
from palmguard.features import build_monthly_panel_df

logger = logging.getLogger(__name__)

COVERAGE_COLUMNS = [
    "series_id",
    "model",
    "interval_method",
    "split",
    "horizon",
    "nominal_level",
    "n_eval",
    "coverage",
    "coverage_ci_lower",
    "coverage_ci_upper",
    "coverage_error",
    "mean_width",
    "mean_width_pct",
]


class SeriesSelectionRecord(BaseModel):
    """Selection record for a specific series."""

    model_config = ConfigDict(extra="forbid")

    series_id: str
    display_name: str
    champion_model: str
    champion_reason: str
    champion_validation_mase: float
    champion_validation_wape: float
    selected_interval_method: str
    interval_method_reason: str
    all_candidate_mase: dict[str, float]
    all_candidate_wape: dict[str, float]
    within_tie_threshold_models: list[str]


class FullSelectionRecord(BaseModel):
    """Container for project selection decisions written prior to holdout scoring."""

    model_config = ConfigDict(extra="forbid")

    project_name: str
    version: str
    timestamp_utc: str
    frozen_vintage_date: str
    selection_rules: list[str]
    series: dict[str, SeriesSelectionRecord]


def compile_validation_metrics(
    predictions_df: pd.DataFrame,
    panel_df: pd.DataFrame,
    cfg: ProjectConfig,
) -> pd.DataFrame:
    """Compile comprehensive validation metrics per series, model, and horizon.

    Output columns: [series_id, model, split, horizon, n_eval, mae, rmse, mase, wape, bias, fit_failures]
    """
    records: list[dict[str, Any]] = []

    for sid in predictions_df["series_id"].unique():
        s_panel = panel_df[panel_df["series_id"] == sid].set_index("month")["value"]
        sub_s = predictions_df[predictions_df["series_id"] == sid]

        for m_id in sub_s["model"].unique():
            sub_m = sub_s[sub_s["model"] == m_id]
            fit_failures = int(sub_m["fit_failed"].sum()) if "fit_failed" in sub_m.columns else 0

            # 1. Per horizon
            for h in cfg.horizons:
                sub_h = sub_m[sub_m["horizon"] == h].dropna(subset=["actual"])
                if sub_h.empty:
                    continue

                scales = [
                    calculate_naive_scale(s_panel.loc[:orig].values)
                    for orig in sub_h["origin"].unique()
                ]
                mean_scale = float(np.mean(scales)) if scales else 1.0

                yt = sub_h["actual"].values
                yp = sub_h["prediction"].values

                records.append(
                    {
                        "series_id": sid,
                        "model": m_id,
                        "split": "validation",
                        "horizon": h,
                        "n_eval": len(yt),
                        "mae": round(calculate_mae(yt, yp), 4),
                        "rmse": round(calculate_rmse(yt, yp), 4),
                        "mase": round(calculate_mase(yt, yp, scale=mean_scale), 4),
                        "wape": round(calculate_wape(yt, yp), 4),
                        "bias": round(calculate_bias(yt, yp), 4),
                        "fit_failures": fit_failures,
                    }
                )

            # 2. Pooled across all horizons
            sub_all = sub_m.dropna(subset=["actual"])
            if not sub_all.empty:
                scales_all = [
                    calculate_naive_scale(s_panel.loc[:orig].values)
                    for orig in sub_all["origin"].unique()
                ]
                mean_scale_all = float(np.mean(scales_all)) if scales_all else 1.0
                yt_all = sub_all["actual"].values
                yp_all = sub_all["prediction"].values

                records.append(
                    {
                        "series_id": sid,
                        "model": m_id,
                        "split": "validation",
                        "horizon": "pooled",
                        "n_eval": len(yt_all),
                        "mae": round(calculate_mae(yt_all, yp_all), 4),
                        "rmse": round(calculate_rmse(yt_all, yp_all), 4),
                        "mase": round(calculate_mase(yt_all, yp_all, scale=mean_scale_all), 4),
                        "wape": round(calculate_wape(yt_all, yp_all), 4),
                        "bias": round(calculate_bias(yt_all, yp_all), 4),
                        "fit_failures": fit_failures,
                    }
                )

    metrics_df = pd.DataFrame(records)
    return metrics_df


def origin_price_map(series_preds: pd.DataFrame, champion: str) -> dict[str, float]:
    """Observed level at each origin: B1's forecast equals y[origin]; champion's first row otherwise."""
    ordered = series_preds.sort_values(["origin", "horizon"])
    champ_first = ordered[ordered["model"] == champion].groupby("origin")["prediction"].first()
    b1_first = ordered[ordered["model"] == "B1"].groupby("origin")["prediction"].first()
    prices = b1_first.reindex(champ_first.index).fillna(champ_first)
    return {str(origin): float(price) for origin, price in prices.items()}


def summarise_interval_coverage(
    intervals_df: pd.DataFrame,
    series_id: str,
    model: str,
    interval_method: str,
    split: str,
) -> pd.DataFrame:
    """Empirical coverage per horizon and nominal level, with Wilson interval and mean width.

    coverage_error is empirical coverage minus nominal (positive = intervals too wide).
    """
    records: list[dict[str, Any]] = []
    for (horizon, level), grp in intervals_df.groupby(["horizon", "nominal_level"], sort=True):
        m = evaluate_prediction_intervals(
            grp["actual"].values,
            grp["lower_bound"].values,
            grp["upper_bound"].values,
            nominal_level=float(level),
        )
        records.append(
            {
                "series_id": series_id,
                "model": model,
                "interval_method": interval_method,
                "split": split,
                "horizon": int(horizon),
                "nominal_level": float(level),
                "n_eval": m.eval_count,
                "coverage": round(m.coverage.coverage_rate, 4),
                "coverage_ci_lower": round(m.coverage.ci_lower, 4),
                "coverage_ci_upper": round(m.coverage.ci_upper, 4),
                "coverage_error": round(m.coverage.coverage_rate - float(level), 4),
                "mean_width": round(m.mean_width, 4),
                "mean_width_pct": round(m.mean_width_pct, 2),
            }
        )
    return pd.DataFrame(records, columns=COVERAGE_COLUMNS)


def select_champion_and_interval(
    series_id: str,
    predictions_df: pd.DataFrame,
    panel_df: pd.DataFrame,
    cfg: ProjectConfig,
) -> tuple[SeriesSelectionRecord, ConformalTracker, pd.DataFrame]:
    """Apply selection rules to choose champion forecaster and conformal interval method.

    Also returns the validation coverage table for both interval methods.
    """
    s_panel = panel_df[panel_df["series_id"] == series_id].set_index("month")["value"]
    sub_s = predictions_df[predictions_df["series_id"] == series_id]

    simplicity_order = cfg.modelling.selection.simplicity_order
    tie_threshold = cfg.modelling.selection.relative_mase_tie_threshold

    # 1. Compute pooled validation MASE and WAPE per candidate
    mase_map: dict[str, float] = {}
    wape_map: dict[str, float] = {}

    for m in simplicity_order:
        sub_m = sub_s[sub_s["model"] == m].dropna(subset=["actual"])
        if sub_m.empty:
            continue
        scales = [
            calculate_naive_scale(s_panel.loc[:orig].values) for orig in sub_m["origin"].unique()
        ]
        mean_scale = float(np.mean(scales)) if scales else 1.0
        mase_val = calculate_mase(
            sub_m["actual"].values, sub_m["prediction"].values, scale=mean_scale
        )
        wape_val = calculate_wape(sub_m["actual"].values, sub_m["prediction"].values)
        mase_map[m] = float(mase_val)
        wape_map[m] = float(wape_val)

    # 2. Select champion point forecaster
    best_m = min(mase_map.keys(), key=lambda k: mase_map[k])
    best_mase = mase_map[best_m]

    eligible = [
        m
        for m in simplicity_order
        if m in mase_map and (mase_map[m] - best_mase) / best_mase <= tie_threshold
    ]
    champion = eligible[0]
    if champion == best_m:
        reason = f"Lowest pooled validation MASE ({best_mase:.4f})."
    else:
        reason = (
            f"Candidate {champion} (MASE {mase_map[champion]:.4f}) is simpler than best {best_m} "
            f"(MASE {best_mase:.4f}) and falls within {tie_threshold * 100:.1f}% relative MASE threshold."
        )

    # 3. Select interval method (C1 vs C2) built on the champion
    champ_preds = sub_s[sub_s["model"] == champion]
    origin_prices = origin_price_map(sub_s, champion)

    method_evals: dict[str, dict[str, float]] = {}
    trackers: dict[str, ConformalTracker] = {}
    coverage_frames: list[pd.DataFrame] = []

    for method in ["C1", "C2"]:
        tr = ConformalTracker(
            nominal_levels=cfg.conformal.levels,
            window_size=cfg.conformal.window_size,
            aci_gamma=cfg.conformal.aci_gamma,
        )
        trackers[method] = tr
        intervals_df = replay_conformal_intervals(tr, champ_preds, origin_prices, method)
        cov_df = summarise_interval_coverage(
            intervals_df, series_id, champion, method, "validation"
        )
        coverage_frames.append(cov_df)
        method_evals[method] = {
            "cov_err": float(cov_df["coverage_error"].abs().mean()) if not cov_df.empty else 0.0,
            "mean_width": float(cov_df["mean_width"].mean()) if not cov_df.empty else 0.0,
        }

    # Choice between C1 and C2: lowest coverage error first, mean width second
    best_iv_method = min(
        method_evals.keys(),
        key=lambda m: (method_evals[m]["cov_err"], method_evals[m]["mean_width"]),
    )
    iv_reason = (
        f"{best_iv_method} selected by lower validation coverage error "
        f"({method_evals[best_iv_method]['cov_err']:.4f} vs {method_evals['C1' if best_iv_method == 'C2' else 'C2']['cov_err']:.4f})."
    )

    sec_rec = SeriesSelectionRecord(
        series_id=series_id,
        display_name=cfg.targets[series_id].display_name if series_id in cfg.targets else series_id,
        champion_model=champion,
        champion_reason=reason,
        champion_validation_mase=mase_map[champion],
        champion_validation_wape=wape_map[champion],
        selected_interval_method=best_iv_method,
        interval_method_reason=iv_reason,
        all_candidate_mase=mase_map,
        all_candidate_wape=wape_map,
        within_tie_threshold_models=eligible,
    )

    coverage_df = pd.concat(coverage_frames, ignore_index=True)
    coverage_df["selected"] = coverage_df["interval_method"] == best_iv_method
    return sec_rec, trackers[best_iv_method], coverage_df


def execute_validation_selection(
    root: Path = Path("."),
    config_path: Path = Path("config/project.yaml"),
) -> tuple[FullSelectionRecord, pd.DataFrame]:
    """Execute validation selection pipeline, save artifacts, and write selection_record.json."""
    cfg_file = config_path if config_path.is_absolute() else root / config_path
    cfg = load_config(cfg_file)
    raw_root = root / cfg.paths.raw_dir
    reports_dir = root / cfg.paths.reports_dir
    artifacts_dir = root / cfg.paths.artifacts_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load predictions
    p_base_path = reports_dir / "predictions_baselines_validation.parquet"
    p_lgbm_path = reports_dir / "predictions_lgbm_validation.parquet"
    if not p_base_path.is_file() or not p_lgbm_path.is_file():
        raise FileNotFoundError(
            f"Backtest predictions not found in {reports_dir}. Run 'palmguard backtest' first."
        )

    df_base = pd.read_parquet(p_base_path)
    df_lgbm = pd.read_parquet(p_lgbm_path)
    preds_all = pd.concat([df_base, df_lgbm], ignore_index=True)

    # Save combined predictions.parquet
    combined_parquet = reports_dir / "predictions.parquet"
    preds_all.to_parquet(combined_parquet, index=False)

    # 2. Build panel and compile validation_metrics.csv
    panel_df = build_monthly_panel_df(raw_root, as_of=cfg.project.frozen_vintage_date)
    metrics_df = compile_validation_metrics(preds_all, panel_df, cfg)
    metrics_csv = reports_dir / "validation_metrics.csv"
    metrics_df.to_csv(metrics_csv, index=False)

    # 3. Select champion and intervals for each series
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    series_records: dict[str, SeriesSelectionRecord] = {}
    conformal_states: dict[str, Any] = {}
    coverage_frames: list[pd.DataFrame] = []

    for sid in cfg.targets.keys():
        s_rec, final_tracker, cov_df = select_champion_and_interval(sid, preds_all, panel_df, cfg)
        series_records[sid] = s_rec
        coverage_frames.append(cov_df)

        # Serialise conformal state
        conformal_states[sid] = {
            "interval_method": s_rec.selected_interval_method,
            "aci_alphas": {
                f"h{h}_lvl{lvl}": float(alpha)
                for (h, lvl), alpha in final_tracker.aci_alphas.items()
            },
            "residuals_count": {
                f"h{h}": len(final_tracker.residual_pool.get(h, [])) for h in [1, 2, 3]
            },
        }

    # Validation coverage for both interval methods (Objective O3 evidence)
    pd.concat(coverage_frames, ignore_index=True).to_csv(
        reports_dir / "validation_coverage.csv", index=False
    )

    full_selection = FullSelectionRecord(
        project_name=cfg.project.name,
        version=cfg.project.version,
        timestamp_utc=now_utc,
        frozen_vintage_date=cfg.project.frozen_vintage_date,
        selection_rules=[
            "1. Lowest pooled validation MASE wins.",
            "2. If within 2% relative MASE tie threshold, the simpler candidate wins (Order: B1, B2, B3, B4, M1, M2).",
            "3. Conformal interval method chosen by lower mean |empirical coverage - nominal| on validation first, mean width second.",
        ],
        series=series_records,
    )

    # 4. Write artifacts/champion/selection_record.json
    selection_json = artifacts_dir / "selection_record.json"
    selection_json.write_text(full_selection.model_dump_json(indent=2), encoding="utf-8")

    # 5. Write artifacts/champion/conformal_state.json
    conformal_json = artifacts_dir / "conformal_state.json"
    conformal_json.write_text(json.dumps(conformal_states, indent=2), encoding="utf-8")

    # 6. Write artifacts/champion/metadata.json
    metadata = {
        "project_name": cfg.project.name,
        "version": cfg.project.version,
        "frozen_vintage_date": cfg.project.frozen_vintage_date,
        "selected_champions": {sid: s_rec.champion_model for sid, s_rec in series_records.items()},
        "selected_intervals": {
            sid: s_rec.selected_interval_method for sid, s_rec in series_records.items()
        },
        "timestamp_utc": now_utc,
    }
    metadata_json = artifacts_dir / "metadata.json"
    metadata_json.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return full_selection, metrics_df
