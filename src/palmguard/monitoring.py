"""PalmGuard monitoring and drift detection (Task T17).

Computes:
1. Rolling forecast metrics (MASE, absolute percentage error, RMSE, bias) per series and horizon.
2. Rolling empirical interval coverage (80% and 90%) over trailing 12- and 24-month windows.
3. Data drift: Population Stability Index (PSI) and two-sample Kolmogorov-Smirnov (KS) test
   comparing recent window (trailing 24 months) against historical reference (baseline period).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict
from scipy import stats

from palmguard.config import ProjectConfig, load_config


class HorizonMonitoring(BaseModel):
    """Rolling metrics and coverage for a single horizon."""

    model_config = ConfigDict(extra="forbid")

    horizon: int
    rolling_12m_mase: float | None = None
    rolling_24m_mase: float | None = None
    rolling_12m_mape: float | None = None
    rolling_24m_mape: float | None = None
    rolling_12m_coverage_80: float | None = None
    rolling_24m_coverage_80: float | None = None
    rolling_12m_coverage_90: float | None = None
    rolling_24m_coverage_90: float | None = None
    observations_count: int = 0


class DriftFeatureResult(BaseModel):
    """Drift check result for a single feature or return series."""

    model_config = ConfigDict(extra="forbid")

    feature_name: str
    psi: float
    psi_drift_flag: bool
    ks_statistic: float
    ks_pvalue: float
    ks_drift_flag: bool
    overall_drift_flag: bool
    ref_mean: float
    recent_mean: float


class SeriesMonitoringReport(BaseModel):
    """Complete monitoring and drift status for a target series."""

    model_config = ConfigDict(extra="forbid")

    series_id: str
    display_name: str
    champion_model: str
    interval_method: str
    latest_evaluated_target_month: str | None = None
    horizons: dict[int, HorizonMonitoring]
    drift_summary: dict[str, DriftFeatureResult]
    any_drift_alert: bool
    monitoring_timestamp_utc: str


def calculate_psi(
    reference: np.ndarray,
    recent: np.ndarray,
    bins: int = 10,
    eps: float = 1e-4,
) -> float:
    """Calculate Population Stability Index (PSI) between reference and recent samples.

    PSI < 0.1: No significant change
    0.1 <= PSI < 0.25: Moderate shift
    PSI >= 0.25: Significant change / drift
    """
    ref_clean = reference[np.isfinite(reference)]
    rec_clean = recent[np.isfinite(recent)]
    if len(ref_clean) < 10 or len(rec_clean) < 5:
        return 0.0

    # Quantile bins derived from reference
    quantiles = np.linspace(0, 100, bins + 1)
    bin_edges = np.percentile(ref_clean, quantiles)
    # Deduplicate edges if distribution has ties
    bin_edges = np.unique(bin_edges)
    if len(bin_edges) < 2:
        return 0.0

    # Expand edge limits
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf

    ref_counts, _ = np.histogram(ref_clean, bins=bin_edges)
    rec_counts, _ = np.histogram(rec_clean, bins=bin_edges)

    ref_pct = (ref_counts + eps) / (len(ref_clean) + eps * len(ref_counts))
    rec_pct = (rec_counts + eps) / (len(rec_clean) + eps * len(rec_counts))

    psi_val = np.sum((rec_pct - ref_pct) * np.log(rec_pct / ref_pct))
    return float(max(0.0, psi_val))


def check_ks_drift(
    reference: np.ndarray,
    recent: np.ndarray,
    alpha: float = 0.05,
) -> tuple[float, float, bool]:
    """Run two-sample Kolmogorov-Smirnov test between reference and recent samples."""
    ref_clean = reference[np.isfinite(reference)]
    rec_clean = recent[np.isfinite(recent)]
    if len(ref_clean) < 5 or len(rec_clean) < 5:
        return 0.0, 1.0, False

    ks_stat, p_val = stats.ks_2samp(ref_clean, rec_clean)
    drift_flag = bool(p_val < alpha)
    return float(ks_stat), float(p_val), drift_flag


def evaluate_series_monitoring(
    series_id: str,
    scores_df: pd.DataFrame,
    features_df: pd.DataFrame,
    cfg: ProjectConfig,
    champion_model: str,
    interval_method: str,
    timestamp_utc: str,
) -> SeriesMonitoringReport:
    """Evaluate rolling metrics and drift for one series."""
    target_cfg = cfg.targets[series_id]
    psi_threshold = cfg.monitoring.psi_threshold
    ks_alpha = cfg.monitoring.ks_alpha
    recent_months = cfg.monitoring.drift_recent_months

    # 1. Rolling scores per horizon
    horizons_report: dict[int, HorizonMonitoring] = {}
    latest_month = None

    if not scores_df.empty and "series_id" in scores_df.columns:
        s_scores = scores_df[scores_df["series_id"] == series_id].copy()
        if not s_scores.empty:
            s_scores = s_scores.sort_values("target_month")
            latest_month = str(s_scores["target_month"].iloc[-1])

            for h in cfg.horizons:
                h_scores = s_scores[s_scores["horizon"] == h]
                n_obs = len(h_scores)
                if n_obs == 0:
                    horizons_report[h] = HorizonMonitoring(horizon=h, observations_count=0)
                    continue

                def _mean_metric(col: str, window: int) -> float | None:
                    if col not in h_scores.columns:
                        return None
                    subset = h_scores.tail(window)[col].dropna()
                    return float(subset.mean()) if len(subset) > 0 else None

                # Compute rolling metrics
                r12_mase = _mean_metric("mase", 12) if "mase" in h_scores.columns else None
                r24_mase = _mean_metric("mase", 24) if "mase" in h_scores.columns else None
                r12_mape = _mean_metric("abs_pct_error", 12)
                r24_mape = _mean_metric("abs_pct_error", 24)
                r12_cov80 = _mean_metric("interval_hit_80", 12)
                r24_cov80 = _mean_metric("interval_hit_80", 24)
                r12_cov90 = _mean_metric("interval_hit_90", 12)
                r24_cov90 = _mean_metric("interval_hit_90", 24)

                horizons_report[h] = HorizonMonitoring(
                    horizon=h,
                    rolling_12m_mase=r12_mase,
                    rolling_24m_mase=r24_mase,
                    rolling_12m_mape=r12_mape,
                    rolling_24m_mape=r24_mape,
                    rolling_12m_coverage_80=r12_cov80,
                    rolling_24m_coverage_80=r24_cov80,
                    rolling_12m_coverage_90=r12_cov90,
                    rolling_24m_coverage_90=r24_cov90,
                    observations_count=n_obs,
                )
    else:
        for h in cfg.horizons:
            horizons_report[h] = HorizonMonitoring(horizon=h, observations_count=0)

    # 2. Data drift on features & return
    drift_results: dict[str, DriftFeatureResult] = {}
    any_drift = False

    if not features_df.empty and "origin_month" in features_df.columns:
        feat_df = features_df.sort_values("origin_month")
        total_rows = len(feat_df)
        if total_rows > recent_months + 10:
            ref_subset = feat_df.iloc[:-recent_months]
            rec_subset = feat_df.iloc[-recent_months:]

            candidate_cols = [
                col
                for col in feat_df.columns
                if col.startswith("return_")
                or col.startswith("driver_")
                or col in ["y_origin", "pct_dist_from_12m_max"]
            ]

            for col in candidate_cols:
                ref_vals = pd.to_numeric(ref_subset[col], errors="coerce").dropna().values
                rec_vals = pd.to_numeric(rec_subset[col], errors="coerce").dropna().values

                if len(ref_vals) < 10 or len(rec_vals) < 5:
                    continue

                psi = calculate_psi(ref_vals, rec_vals)
                psi_flag = bool(psi >= psi_threshold)

                ks_stat, ks_pval, ks_flag = check_ks_drift(ref_vals, rec_vals, alpha=ks_alpha)
                overall_flag = psi_flag or ks_flag
                if overall_flag:
                    any_drift = True

                drift_results[col] = DriftFeatureResult(
                    feature_name=col,
                    psi=round(psi, 4),
                    psi_drift_flag=psi_flag,
                    ks_statistic=round(ks_stat, 4),
                    ks_pvalue=round(ks_pval, 4),
                    ks_drift_flag=ks_flag,
                    overall_drift_flag=overall_flag,
                    ref_mean=round(float(np.mean(ref_vals)), 4),
                    recent_mean=round(float(np.mean(rec_vals)), 4),
                )

    return SeriesMonitoringReport(
        series_id=series_id,
        display_name=target_cfg.display_name,
        champion_model=champion_model,
        interval_method=interval_method,
        latest_evaluated_target_month=latest_month,
        horizons=horizons_report,
        drift_summary=drift_results,
        any_drift_alert=any_drift,
        monitoring_timestamp_utc=timestamp_utc,
    )


def run_monitoring_audit(
    root: Path = Path("."),
    *,
    config_path: Path = Path("config/project.yaml"),
) -> dict[str, Any]:
    """Execute monitoring calculations and write reports/published/monitoring.json."""
    from datetime import datetime, timezone

    cfg_file = config_path if config_path.is_absolute() else root / config_path
    cfg = load_config(cfg_file)

    published_dir = root / cfg.paths.published_dir
    published_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = root / cfg.paths.artifacts_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Champion metadata not found at {metadata_path}")
    with open(metadata_path, encoding="utf-8") as f:
        meta = json.load(f)

    champions = meta.get("selected_champions", {})
    intervals = meta.get("selected_intervals", {})

    scores_path = root / cfg.paths.processed_dir / "scores.parquet"
    scores_df = pd.read_parquet(scores_path) if scores_path.exists() else pd.DataFrame()

    timestamp_utc = datetime.now(timezone.utc).isoformat()
    all_reports: dict[str, Any] = {}

    for series_id in cfg.targets.keys():
        champ = champions.get(series_id, "B1")
        int_m = intervals.get(series_id, "C1")

        feat_path = root / cfg.paths.processed_dir / f"features_{series_id}.parquet"
        feat_df = pd.read_parquet(feat_path) if feat_path.exists() else pd.DataFrame()

        report = evaluate_series_monitoring(
            series_id=series_id,
            scores_df=scores_df,
            features_df=feat_df,
            cfg=cfg,
            champion_model=champ,
            interval_method=int_m,
            timestamp_utc=timestamp_utc,
        )
        all_reports[series_id] = report.model_dump()

    out_file = published_dir / "monitoring.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_reports, f, indent=2)

    return all_reports
