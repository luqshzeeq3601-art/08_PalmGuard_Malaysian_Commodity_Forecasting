"""PalmGuard end-to-end forecasting pipeline (Task T16).

Implements the sequential production pipeline steps:
1. Ingest new snapshots (unless offline) and validate data contracts
2. Features: build monthly panel and feature sets
3. Score: join append-only forecast ledger to newly observed actuals using queries/scoring.sql
4. Forecast: refit frozen champions on expanding window and generate h=1..3 point forecasts + intervals
5. Append: update append-only forecast ledger (validates no past rows mutated)
6. Monitor: execute monitoring audit and drift checks (monitoring.json)
7. Publish: write snapshot of forecast.json, history.parquet, and metadata into reports/published/
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from palmguard.baselines import (
    forecast_arima_b4,
    forecast_ets_b3,
    forecast_naive_b1,
    forecast_seasonal_naive_b2,
)
from palmguard.config import ProjectConfig, load_config
from palmguard.conformal import ConformalTracker, replay_conformal_intervals
from palmguard.contracts import run_data_quality_gate
from palmguard.features import build_features_df, build_monthly_panel_df
from palmguard.http import create_http_client
from palmguard.ingest.datagovmy import ingest_all_datagovmy
from palmguard.ingest.worldbank import ingest_worldbank_pink_sheet
from palmguard.monitoring import run_monitoring_audit


class ForecastRecord(BaseModel):
    """Single horizon forecast output ready for ledger and publishing."""

    model_config = ConfigDict(extra="forbid")

    series_id: str
    model_id: str
    model_version: str
    origin_month: str
    target_month: str
    horizon: int
    y_origin: float
    y_pred: float
    q80_lower: float
    q80_upper: float
    q90_lower: float
    q90_upper: float
    conformal_method: str
    forecast_timestamp_utc: str


def validate_ledger_immutability(
    existing_ledger: pd.DataFrame,
    updated_ledger: pd.DataFrame,
    key_cols: list[str] | None = None,
) -> None:
    """Assert that no previously written ledger rows have had their values changed."""
    if existing_ledger.empty:
        return

    if key_cols is None:
        key_cols = ["series_id", "origin_month", "target_month", "horizon", "model_id"]

    # Check that all existing rows are present in updated ledger with identical values
    merged = existing_ledger.merge(
        updated_ledger,
        on=key_cols,
        suffixes=("_old", "_new"),
        how="inner",
    )
    if len(merged) != len(existing_ledger):
        raise ValueError(
            f"Ledger immutability violated: existing rows ({len(existing_ledger)}) "
            f"missing in updated ledger ({len(merged)})"
        )

    # Check key numeric columns
    check_cols = ["y_pred", "q80_lower", "q80_upper", "q90_lower", "q90_upper"]
    for c in check_cols:
        if f"{c}_old" in merged.columns and f"{c}_new" in merged.columns:
            diff = np.abs(merged[f"{c}_old"] - merged[f"{c}_new"])
            if (diff > 1e-4).any():
                bad = merged[diff > 1e-4]
                raise ValueError(
                    f"Ledger immutability violated: column '{c}' changed for "
                    f"{len(bad)} rows: {bad[key_cols].to_dict('records')}"
                )


def run_pipeline_score_step(
    root: Path,
    cfg: ProjectConfig,
    panel_df: pd.DataFrame,
) -> pd.DataFrame:
    """Score existing forecast ledger against observed actuals via queries/scoring.sql."""
    ledger_path = root / cfg.paths.processed_dir / "forecast_ledger.parquet"
    scores_path = root / cfg.paths.processed_dir / "scores.parquet"

    if not ledger_path.exists():
        empty_scores = pd.DataFrame()
        return empty_scores

    ledger_df = pd.read_parquet(ledger_path)
    if ledger_df.empty:
        return pd.DataFrame()

    scoring_sql_path = root / cfg.paths.queries_dir / "scoring.sql"
    sql_text = scoring_sql_path.read_text(encoding="utf-8")

    con = duckdb.connect()
    con.register("forecast_ledger", ledger_df)
    con.register("monthly_panel", panel_df)

    scored_df = con.sql(sql_text).df()
    con.close()

    if not scored_df.empty:
        scores_path.parent.mkdir(parents=True, exist_ok=True)
        scored_df.to_parquet(scores_path, index=False)

    return scored_df


def refit_and_forecast_series(
    series_id: str,
    champion_id: str,
    interval_method: str,
    panel_df: pd.DataFrame,
    features_df: pd.DataFrame,
    cfg: ProjectConfig,
    timestamp_utc: str,
) -> list[ForecastRecord]:
    """Refit the frozen champion model configuration on available data and forecast h=1..3."""
    target_series_panel = panel_df[panel_df["series_id"] == series_id].sort_values("month").copy()
    if target_series_panel.empty:
        raise ValueError(f"No panel data found for series {series_id}")

    # Available origin is the last month in panel
    origin_month = str(target_series_panel["month"].iloc[-1])
    y_origin = float(target_series_panel["value"].iloc[-1])
    y_train = target_series_panel["value"].values

    # Point forecasts for h=1, 2, 3
    if champion_id == "B1":
        y_preds = forecast_naive_b1(y_train, horizons=cfg.horizons)
    elif champion_id == "B2":
        y_preds = forecast_seasonal_naive_b2(y_train, horizons=cfg.horizons, season_length=12)
    elif champion_id == "B3":
        y_preds, _, _ = forecast_ets_b3(y_train, horizons=cfg.horizons)
    elif champion_id == "B4":
        y_preds, _, _ = forecast_arima_b4(
            y_train,
            order=(0, 1, 1),
            horizons=cfg.horizons,
        )
    else:
        # Fallback to naive if unknown or baseline
        y_preds = forecast_naive_b1(y_train, horizons=cfg.horizons)

    # Initialize conformal tracker and load historical residuals
    tracker = ConformalTracker(
        nominal_levels=cfg.conformal.levels,
        window_size=cfg.conformal.window_size,
        aci_gamma=cfg.conformal.aci_gamma,
    )

    # Replay the champion over earlier origins so residuals and ACI state are warmed
    hist_rows: list[dict[str, Any]] = []
    hist_origin_prices: dict[str, float] = {}
    for t_idx in range(12, len(y_train) - 3):
        hist_orig_month = str(target_series_panel["month"].iloc[t_idx])
        hist_origin_prices[hist_orig_month] = float(y_train[t_idx])
        sub_train = y_train[: t_idx + 1]

        if champion_id == "B1":
            sub_preds = forecast_naive_b1(sub_train, horizons=cfg.horizons)
        elif champion_id == "B3":
            sub_preds, _, _ = forecast_ets_b3(sub_train, horizons=cfg.horizons)
        elif champion_id == "B4":
            sub_preds, _, _ = forecast_arima_b4(sub_train, order=(0, 1, 1), horizons=cfg.horizons)
        else:
            sub_preds = forecast_naive_b1(sub_train, horizons=cfg.horizons)

        for h in cfg.horizons:
            act_idx = t_idx + h
            if act_idx < len(y_train):
                hist_rows.append(
                    {
                        "origin": hist_orig_month,
                        "target": str(target_series_panel["month"].iloc[act_idx]),
                        "horizon": h,
                        "actual": float(y_train[act_idx]),
                        "prediction": float(sub_preds[h]),
                    }
                )

    replay_conformal_intervals(
        tracker, pd.DataFrame(hist_rows), hist_origin_prices, interval_method
    )
    tracker.apply_observed_aci_updates(origin_month)

    records: list[ForecastRecord] = []
    origin_dt = pd.to_datetime(origin_month)

    for h in cfg.horizons:
        target_dt = origin_dt + pd.DateOffset(months=h)
        target_month = target_dt.strftime("%Y-%m-%d")
        yp = float(y_preds[h])

        intervals = tracker.forecast_intervals(
            origin_month=origin_month,
            horizon=h,
            origin_price=y_origin,
            point_forecast=yp,
            method=interval_method,
        )

        int80 = intervals.get(0.80)
        int90 = intervals.get(0.90)

        rec = ForecastRecord(
            series_id=series_id,
            model_id=champion_id,
            model_version=f"champion_{champion_id}_v{cfg.project.version}",
            origin_month=origin_month,
            target_month=target_month,
            horizon=h,
            y_origin=round(y_origin, 4),
            y_pred=round(yp, 4),
            q80_lower=round(int80.lower_bound, 4) if int80 else round(yp * 0.9, 4),
            q80_upper=round(int80.upper_bound, 4) if int80 else round(yp * 1.1, 4),
            q90_lower=round(int90.lower_bound, 4) if int90 else round(yp * 0.85, 4),
            q90_upper=round(int90.upper_bound, 4) if int90 else round(yp * 1.15, 4),
            conformal_method=interval_method,
            forecast_timestamp_utc=timestamp_utc,
        )
        records.append(rec)

    return records


def execute_pipeline(
    root: Path = Path("."),
    *,
    config_path: Path = Path("config/project.yaml"),
    mode: str = "incremental",
    offline: bool = True,
) -> dict[str, Any]:
    """Execute full sequential pipeline: ingest, features, score, forecast, monitor, publish."""
    cfg_file = config_path if config_path.is_absolute() else root / config_path
    cfg = load_config(cfg_file)
    timestamp_utc = datetime.now(timezone.utc).isoformat()

    print(f"[*] Starting PalmGuard Pipeline (mode={mode}, offline={offline})...")

    # Step 1: Ingest & Contract Gate G1
    raw_root = root / cfg.paths.raw_dir
    if not offline:
        print("[1/6] Ingesting new source snapshots...")
        with create_http_client() as client:
            wb_res, _, _ = ingest_worldbank_pink_sheet(raw_root, client)
            print(f"      worldbank/pink_sheet: {wb_res.status}")
            for ds_id, res in ingest_all_datagovmy(raw_root, client, mode=mode).items():  # type: ignore[arg-type]
                print(f"      {res.manifest.source}/{ds_id}: {res.status}")

    print("[1/6] Running data quality audit and contracts...")
    quality_audit = run_data_quality_gate(config=cfg, root=root)
    if not quality_audit.gate_g1_passed:
        raise RuntimeError("Pipeline stopped: Data quality gate failed.")

    # Step 2: Build monthly panel and features
    # Offline runs reproduce the frozen vintage; live runs use every snapshot retrieved so far.
    as_of = cfg.project.frozen_vintage_date if offline else timestamp_utc[:10]
    print(f"[2/6] Building DuckDB monthly panel and feature sets (as of {as_of})...")
    panel_df = build_monthly_panel_df(raw_root, as_of=as_of)

    # Step 3: Score previous forecasts against new actuals
    print("[3/6] Scoring forecast ledger against observed actuals...")
    scored_df = run_pipeline_score_step(root=root, cfg=cfg, panel_df=panel_df)
    print(f"      Scored {len(scored_df)} historical forecasts.")

    # Step 4: Load champion selection and generate new forecasts
    print("[4/6] Refitting frozen champions and producing forecasts...")
    meta_path = root / cfg.paths.artifacts_dir / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"Champion metadata not found at {meta_path}. Run 'palmguard select' first."
        )
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    champions = meta.get("selected_champions", {})
    intervals = meta.get("selected_intervals", {})

    new_forecast_records: list[ForecastRecord] = []
    for series_id in cfg.targets.keys():
        champ_id = champions.get(series_id, "B1")
        int_m = intervals.get(series_id, "C1")
        feat_df = build_features_df(panel_df, target_series=series_id)

        # Save latest features to processed
        feat_out = root / cfg.paths.processed_dir / f"features_{series_id}.parquet"
        feat_df.to_parquet(feat_out, index=False)

        recs = refit_and_forecast_series(
            series_id=series_id,
            champion_id=champ_id,
            interval_method=int_m,
            panel_df=panel_df,
            features_df=feat_df,
            cfg=cfg,
            timestamp_utc=timestamp_utc,
        )
        new_forecast_records.extend(recs)

    # Step 5: Append to ledger with immutability validation
    print("[5/6] Updating append-only forecast ledger...")
    ledger_path = root / cfg.paths.processed_dir / "forecast_ledger.parquet"
    new_rows_df = pd.DataFrame([r.model_dump() for r in new_forecast_records])

    if ledger_path.exists():
        existing_ledger = pd.read_parquet(ledger_path)
        # Filter out existing matching origin forecasts if re-running idempotently
        keys = ["series_id", "origin_month", "target_month", "horizon", "model_id"]
        overlap = existing_ledger.merge(
            new_rows_df, on=keys, how="inner", suffixes=("_old", "_new")
        )
        if not overlap.empty:
            validate_ledger_immutability(existing_ledger, existing_ledger)
            # Retain existing ledger unmodified and republish the forecasts already issued
            updated_ledger = existing_ledger
            issued = existing_ledger.merge(new_rows_df[keys], on=keys, how="inner")
            new_forecast_records = [ForecastRecord(**row) for row in issued.to_dict("records")]
            print("      No new origin month detected; ledger unmodified (idempotent).")
        else:
            updated_ledger = pd.concat([existing_ledger, new_rows_df], ignore_index=True)
            validate_ledger_immutability(existing_ledger, updated_ledger)
            updated_ledger.to_parquet(ledger_path, index=False)
            print(f"      Appended {len(new_rows_df)} rows to forecast ledger.")
    else:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        new_rows_df.to_parquet(ledger_path, index=False)
        updated_ledger = new_rows_df
        print(f"      Initialized forecast ledger with {len(new_rows_df)} rows.")

    # Step 6: Monitor & Publish artifacts
    print("[6/6] Executing drift monitoring and publishing artifacts...")
    mon_reports = run_monitoring_audit(root=root, config_path=cfg_file)

    published_dir = root / cfg.paths.published_dir
    published_dir.mkdir(parents=True, exist_ok=True)

    # Publish forecast.json
    pub_forecast_data = {
        "project": cfg.project.name,
        "version": cfg.project.version,
        "published_at_utc": timestamp_utc,
        "disclaimer": cfg.attribution.disclaimer,
        "forecasts": [r.model_dump() for r in new_forecast_records],
    }
    with open(published_dir / "forecast.json", "w", encoding="utf-8") as f:
        json.dump(pub_forecast_data, f, indent=2)

    # Publish latest scores to published/history.parquet
    if not scored_df.empty:
        scored_df.to_parquet(published_dir / "history.parquet", index=False)
    elif ledger_path.exists():
        updated_ledger.to_parquet(published_dir / "history.parquet", index=False)

    print(f"[*] Pipeline run complete at {timestamp_utc}. Published artifacts in {published_dir}")
    return {
        "status": "success",
        "published_at_utc": timestamp_utc,
        "forecast_count": len(new_forecast_records),
        "monitoring": mon_reports,
    }
