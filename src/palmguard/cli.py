"""PalmGuard command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REQUIRED_PACKAGES = [
    "duckdb",
    "fastapi",
    "httpx",
    "lightgbm",
    "matplotlib",
    "mlflow",
    "numpy",
    "openpyxl",
    "pandas",
    "pyarrow",
    "pydantic",
    "scipy",
    "sklearn",
    "statsmodels",
    "streamlit",
    "uvicorn",
    "yaml",
]

WRITABLE_DIRS = ["data/raw", "data/processed", "artifacts/champion", "reports/published"]


def check_duckdb_window() -> bool:
    """Confirm DuckDB evaluates a lag window as the feature layer expects."""
    import duckdb

    rows = duckdb.sql(
        "SELECT x, LAG(x) OVER (ORDER BY x) AS prev FROM (VALUES (1), (2), (3)) t(x) ORDER BY x"
    ).fetchall()
    return rows == [(1, None), (2, 1), (3, 2)]


def run_doctor(root: Path = Path(".")) -> int:
    """Run environment and prerequisite checks (Gate G0)."""
    print("=== PalmGuard System Doctor ===")

    py_ok = (3, 10) <= sys.version_info[:2] < (3, 13)
    print(f"[*] Python version: {sys.version.split()[0]} -> {'PASS' if py_ok else 'FAIL'}")

    pkg_ok = True
    for pkg in REQUIRED_PACKAGES:
        try:
            mod = __import__(pkg)
            print(f"[*] Package {pkg}: {getattr(mod, '__version__', 'installed')}")
        except ImportError:
            pkg_ok = False
            print(f"[!] Package {pkg}: MISSING")

    try:
        duckdb_ok = check_duckdb_window()
    except Exception as e:
        duckdb_ok = False
        print(f"[!] DuckDB window function: FAIL ({e})")
    else:
        print(f"[*] DuckDB window function: {'PASS' if duckdb_ok else 'FAIL'}")

    dir_ok = True
    for d in WRITABLE_DIRS:
        p = root / d
        test_file = p / ".write_test"
        try:
            p.mkdir(parents=True, exist_ok=True)
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
        except OSError as e:
            dir_ok = False
            print(f"[!] Directory {d}: NOT WRITABLE ({e})")
    print(f"[*] Writable directories: {'PASS' if dir_ok else 'FAIL'}")

    all_ok = py_ok and pkg_ok and duckdb_ok and dir_ok
    print(f"=== Doctor result: {'PASS' if all_ok else 'FAIL'} ===")
    return 0 if all_ok else 1


def run_ingest(
    root: Path = Path("."),
    *,
    config_path: Path = Path("config/project.yaml"),
    mode: str = "backfill",
    offline: bool = False,
) -> int:
    """Ingest raw sources (unless --offline) and run Gate G1 data quality audit."""
    from palmguard.config import load_config
    from palmguard.contracts import run_data_quality_gate
    from palmguard.http import create_http_client
    from palmguard.ingest.datagovmy import ingest_all_datagovmy
    from palmguard.ingest.worldbank import ingest_worldbank_pink_sheet

    cfg_file = config_path if config_path.is_absolute() else root / config_path
    cfg = load_config(cfg_file)
    raw_root = root / cfg.paths.raw_dir

    if not offline:
        with create_http_client() as client:
            wb_res, _, _ = ingest_worldbank_pink_sheet(raw_root, client)
            print(f"[*] worldbank/pink_sheet: {wb_res.status} ({wb_res.manifest.snapshot_id})")
            dgm_res = ingest_all_datagovmy(raw_root, client, mode=mode)  # type: ignore[arg-type]
            for ds_id, res in dgm_res.items():
                print(
                    f"[*] {res.manifest.source}/{ds_id}: {res.status} ({res.manifest.snapshot_id})"
                )

    audit = run_data_quality_gate(cfg, root=root)
    print(
        f"[*] O1 (palm_wb_myr >= 180 months): {'PASS' if audit.o1_passed else 'FAIL'} ({audit.palm_wb_myr_months} months)"
    )
    print(f"[*] PPI section 4 months: {audit.ppi_oilsfats_my_months}")
    print(f"[*] Selected primary target: {audit.selected_primary_target}")
    print(f"=== Gate G1 result: {'PASS' if audit.gate_g1_passed else 'FAIL'} ===")
    return 0 if audit.gate_g1_passed else 1


def run_features(
    root: Path = Path("."),
    *,
    config_path: Path = Path("config/project.yaml"),
    target_series: str | None = None,
) -> int:
    """Build monthly panel and extract features (Task T07, T08)."""
    from palmguard.config import load_config
    from palmguard.features import build_features_df, build_monthly_panel_df

    cfg_file = config_path if config_path.is_absolute() else root / config_path
    cfg = load_config(cfg_file)
    raw_root = root / cfg.paths.raw_dir

    print(f"[*] Building monthly panel as of vintage {cfg.project.frozen_vintage_date}...")
    panel_df = build_monthly_panel_df(raw_root, as_of=cfg.project.frozen_vintage_date)
    print(
        f"[*] Monthly panel built: {len(panel_df)} total series-month rows across {panel_df['series_id'].nunique()} series."
    )

    targets = [target_series] if target_series else list(cfg.targets.keys())
    for t in targets:
        feats_df = build_features_df(panel_df, target_series=t)
        print(f"[*] Features built for {t}: {len(feats_df)} rows, {len(feats_df.columns)} columns.")

    print("=== Features build: PASS ===")
    return 0


def run_splits(
    root: Path = Path("."),
    *,
    config_path: Path = Path("config/project.yaml"),
    manifest_path: Path = Path("data/processed/split_manifest.json"),
) -> int:
    """Execute Gate G2 verification and freeze split manifest (Task T09)."""
    from palmguard.config import load_config
    from palmguard.splits import run_split_gate

    cfg_file = config_path if config_path.is_absolute() else root / config_path
    cfg = load_config(cfg_file)
    m_path = manifest_path if manifest_path.is_absolute() else root / manifest_path

    ok, manifest = run_split_gate(cfg, root=root, manifest_path=m_path)
    for sid, s in manifest.series.items():
        print(f"[*] Series {sid}:")
        print(f"    - SHA-256: {s.series_sha256[:16]}...")
        print(
            f"    - Total months: {s.total_months_count} ({s.min_series_month} to {s.max_series_month})"
        )
        print(
            f"    - Validation origins: {s.validation_origins_count} ({s.validation_origins_range[0]} to {s.validation_origins_range[1]})"
        )
        print(
            f"    - Validation targets: {s.validation_targets_range[0]} to {s.validation_targets_range[1]}"
        )
        print(
            f"    - Holdout origins: {s.holdout_origins_count} ({s.holdout_origins_range[0]} to {s.holdout_origins_range[1]})"
        )
        print(
            f"    - Holdout targets: {s.holdout_targets_range[0]} to {s.holdout_targets_range[1]}"
        )
        print(
            f"    - Min training months: {s.validation_folds[0].training_months_count} (required >= {s.min_training_months_required})"
        )

    print(f"=== Checkpoint Gate G2 result: {'PASS' if ok else 'FAIL'} ===")
    return 0 if ok else 1


def run_backtest(
    root: Path = Path("."),
    *,
    config_path: Path = Path("config/project.yaml"),
    models: str = "baselines",
    split: str = "validation",
    target_series: str | None = None,
) -> int:
    """Run backtesting for declared models on validation origins (Task T11)."""
    import numpy as np
    import pandas as pd

    from palmguard.baselines import backtest_baselines
    from palmguard.config import load_config
    from palmguard.evaluation import calculate_mase, calculate_naive_scale, calculate_wape
    from palmguard.features import build_monthly_panel_df
    from palmguard.splits import load_split_manifest

    cfg_file = config_path if config_path.is_absolute() else root / config_path
    cfg = load_config(cfg_file)
    raw_root = root / cfg.paths.raw_dir
    manifest_file = root / "data/processed/split_manifest.json"

    if not manifest_file.is_file():
        print(f"[!] Split manifest not found at {manifest_file}. Run 'palmguard splits' first.")
        return 1

    manifest = load_split_manifest(manifest_file)
    panel_df = build_monthly_panel_df(raw_root, as_of=cfg.project.frozen_vintage_date)

    series_keys = [target_series] if target_series else list(manifest.series.keys())
    all_preds_dfs: list[pd.DataFrame] = []

    for sid in series_keys:
        s_manifest = manifest.series[sid]
        folds = s_manifest.validation_folds if split == "validation" else s_manifest.holdout_folds

        print(f"[*] Running {models} backtest on {sid} ({split} split, {len(folds)} origins)...")
        if models in ["baselines", "all"]:
            preds_df, chosen_order = backtest_baselines(
                panel_df,
                series_id=sid,
                folds=folds,
                split_name=split,
                horizons=cfg.horizons,
            )
            print(f"    - B4 chosen ARIMA order: {chosen_order}")
            all_preds_dfs.append(preds_df)

            # Print summary metrics per model across observed actuals
            s_series = panel_df[panel_df["series_id"] == sid].set_index("month")["value"]
            for m_id in ["B1", "B2", "B3", "B4"]:
                sub = preds_df[preds_df["model"] == m_id].dropna(subset=["actual"])
                if not sub.empty:
                    scales = [
                        calculate_naive_scale(s_series.loc[:orig].values)
                        for orig in sub["origin"].unique()
                    ]
                    mean_scale = float(np.mean(scales)) if scales else 1.0
                    mase_val = calculate_mase(
                        sub["actual"].values, sub["prediction"].values, scale=mean_scale
                    )
                    wape_val = calculate_wape(sub["actual"].values, sub["prediction"].values)
                    print(f"    - {m_id}: Pooled MASE = {mase_val:.4f}, WAPE = {wape_val:.4f}")

        if models in ["lgbm", "all"]:
            from palmguard.features import build_features_df
            from palmguard.model import (
                backtest_lgbm,
                generate_grid_configurations,
                select_best_lgbm_params,
            )

            feats_df = build_features_df(panel_df, target_series=sid)
            s_series = panel_df[panel_df["series_id"] == sid].set_index("month")["value"]
            grid_configs = generate_grid_configurations(cfg)

            for lgbm_id in ["M1", "M2"]:
                print(f"    - Tuning {lgbm_id} on validation origins...")
                val_folds = s_manifest.validation_folds
                best_params, _ = select_best_lgbm_params(
                    feats_df,
                    s_series,
                    val_folds,
                    model_id=lgbm_id,
                    grid_configs=grid_configs,
                    horizons=cfg.horizons,
                    seed=cfg.modelling.seed,
                    log_to_mlflow=True,
                    tracking_uri=cfg.paths.mlflow_tracking_uri,
                )
                print(f"    - {lgbm_id} best parameters: {best_params}")

                preds_lgbm, _ = backtest_lgbm(
                    feats_df,
                    series_id=sid,
                    folds=folds,
                    model_id=lgbm_id,
                    params=best_params,
                    split_name=split,
                    horizons=cfg.horizons,
                    seed=cfg.modelling.seed,
                )
                all_preds_dfs.append(preds_lgbm)

                sub = preds_lgbm.dropna(subset=["actual"])
                if not sub.empty:
                    scales = [
                        calculate_naive_scale(s_series.loc[:orig].values)
                        for orig in sub["origin"].unique()
                    ]
                    mean_scale = float(np.mean(scales)) if scales else 1.0
                    mase_val = calculate_mase(
                        sub["actual"].values, sub["prediction"].values, scale=mean_scale
                    )
                    wape_val = calculate_wape(sub["actual"].values, sub["prediction"].values)
                    print(f"    - {lgbm_id}: Pooled MASE = {mase_val:.4f}, WAPE = {wape_val:.4f}")

    if all_preds_dfs:
        combined = pd.concat(all_preds_dfs, ignore_index=True)
        reports_dir = root / cfg.paths.reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_parquet = reports_dir / f"predictions_{models}_{split}.parquet"
        combined.to_parquet(out_parquet, index=False)
        print(f"[*] Predictions written to {out_parquet} ({len(combined)} rows)")

    print(f"=== Backtest {models} on {split}: PASS ===")
    return 0


def run_select(
    root: Path = Path("."),
    *,
    config_path: Path = Path("config/project.yaml"),
) -> int:
    """Execute champion and interval method selection (Checkpoint Gate G3, Task T14)."""
    from palmguard.reporting import execute_validation_selection

    rec, metrics_df = execute_validation_selection(root=root, config_path=config_path)

    print("=== Checkpoint Gate G3: Validation Selection ===")
    for sid, s in rec.series.items():
        print(f"[*] Series: {sid} ({s.display_name})")
        print(f"    - Champion point model: {s.champion_model}")
        print(f"    - Selection reason: {s.champion_reason}")
        print(
            f"    - Validation MASE: {s.champion_validation_mase:.4f}, WAPE: {s.champion_validation_wape:.4f}"
        )
        print(f"    - Conformal interval method: {s.selected_interval_method}")
        print(f"    - Interval reason: {s.interval_method_reason}")

    print("[*] Artifacts written:")
    print("    - reports/validation_metrics.csv")
    print("    - reports/validation_coverage.csv")
    print("    - reports/predictions.parquet")
    print("    - artifacts/champion/selection_record.json")
    print("    - artifacts/champion/conformal_state.json")
    print("    - artifacts/champion/metadata.json")
    print("=== Checkpoint Gate G3: PASS ===")
    return 0


def run_holdout(
    root: Path = Path("."),
    *,
    config_path: Path = Path("config/project.yaml"),
    override_exploratory: bool = False,
    intervals_only: bool = False,
) -> int:
    """Execute formal single-run scoring of all candidates on the 24 holdout origins (Gate G4)."""
    from palmguard.holdout import refresh_holdout_interval_report, run_holdout_scoring

    if intervals_only:
        _, comp_report = refresh_holdout_interval_report(root=root, config_path=config_path)
        print("[*] Interval coverage written: reports/holdout_coverage.csv")
        print(f"[*] Regenerated forecast comparison report: {comp_report}")
        return 0

    try:
        metrics_df, comp_report = run_holdout_scoring(
            root=root,
            config_path=config_path,
            override_exploratory=override_exploratory,
        )
    except RuntimeError as exc:
        print(f"[!] Guard blocked holdout scoring: {exc}")
        return 1

    print("=== Checkpoint Gate G4: Holdout Evaluation Scored ===")
    print(f"[*] Generated holdout metrics: reports/holdout_metrics.csv ({len(metrics_df)} rows)")
    print(f"[*] Generated forecast comparison report: {comp_report}")
    print("[*] Guard file written: artifacts/champion/holdout_guard.json")
    print("=== Checkpoint Gate G4: PASS ===")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="palmguard", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check Python, packages, DuckDB and writable directories")

    p_ingest = sub.add_parser(
        "ingest",
        help="Ingest World Bank and data.gov.my snapshots and run Gate G1 data quality check",
    )
    p_ingest.add_argument(
        "--mode",
        choices=["auto", "backfill", "incremental"],
        default="backfill",
        help="Ingestion mode for data.gov.my datasets (default: backfill)",
    )
    p_ingest.add_argument(
        "--offline",
        action="store_true",
        help="Skip HTTP pulls and validate existing local snapshots only",
    )
    p_ingest.add_argument(
        "--config",
        type=Path,
        default=Path("config/project.yaml"),
        help="Path to project configuration YAML",
    )

    p_features = sub.add_parser(
        "features",
        help="Build monthly panel and extract lag, rolling, and driver features",
    )
    p_features.add_argument(
        "--config",
        type=Path,
        default=Path("config/project.yaml"),
        help="Path to project configuration YAML",
    )
    p_features.add_argument(
        "--target-series",
        type=str,
        default=None,
        help="Specific target series (default: all configured targets)",
    )

    p_splits = sub.add_parser(
        "splits",
        help="Freeze rolling-origin split manifest and run Checkpoint Gate G2",
    )
    p_splits.add_argument(
        "--config",
        type=Path,
        default=Path("config/project.yaml"),
        help="Path to project configuration YAML",
    )
    p_splits.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/split_manifest.json"),
        help="Target output path for split manifest JSON",
    )

    p_backtest = sub.add_parser(
        "backtest",
        help="Run rolling-origin backtest on declared models",
    )
    p_backtest.add_argument(
        "--models",
        type=str,
        default="baselines",
        help="Models to evaluate ('baselines', 'lgbm', or 'all')",
    )
    p_backtest.add_argument(
        "--split",
        choices=["validation", "holdout"],
        default="validation",
        help="Dataset split to evaluate ('validation' or 'holdout')",
    )
    p_backtest.add_argument(
        "--config",
        type=Path,
        default=Path("config/project.yaml"),
        help="Path to project configuration YAML",
    )
    p_backtest.add_argument(
        "--target-series",
        type=str,
        default=None,
        help="Specific target series (default: all configured targets)",
    )

    p_select = sub.add_parser(
        "select",
        help="Select champion model and conformal interval method (Gate G3)",
    )
    p_select.add_argument(
        "--config",
        type=Path,
        default=Path("config/project.yaml"),
        help="Path to project configuration YAML",
    )

    p_holdout = sub.add_parser(
        "holdout",
        help="Score frozen champion and all candidates on holdout split once (Gate G4)",
    )
    p_holdout.add_argument(
        "--config",
        type=Path,
        default=Path("config/project.yaml"),
        help="Path to project configuration YAML",
    )
    p_holdout.add_argument(
        "--override-exploratory",
        action="store_true",
        help="Allow re-running holdout scoring, labelling output exploratory",
    )
    p_holdout.add_argument(
        "--intervals-only",
        action="store_true",
        help="Report champion interval coverage for the already-scored holdout; point metrics untouched",
    )

    # pipeline run
    p_pipe = sub.add_parser("pipeline", help="Execute pipeline steps")
    sub_pipe = p_pipe.add_subparsers(dest="pipeline_subcommand", required=True)
    p_pipe_run = sub_pipe.add_parser(
        "run", help="Run full sequential forecasting pipeline (Gate G5)"
    )
    p_pipe_run.add_argument(
        "--config",
        type=Path,
        default=Path("config/project.yaml"),
        help="Path to project configuration YAML",
    )
    p_pipe_run.add_argument(
        "--mode",
        choices=["incremental", "backfill"],
        default="incremental",
        help="Pipeline execution mode",
    )
    p_pipe_run.add_argument(
        "--offline",
        action="store_true",
        help="Skip ingestion and reproduce the frozen vintage from local snapshots",
    )

    # score
    p_score = sub.add_parser("score", help="Score forecast ledger against observed actuals")
    p_score.add_argument(
        "--config",
        type=Path,
        default=Path("config/project.yaml"),
        help="Path to project configuration YAML",
    )

    # monitor
    p_monitor = sub.add_parser("monitor", help="Run rolling metric and drift evaluation")
    p_monitor.add_argument(
        "--config",
        type=Path,
        default=Path("config/project.yaml"),
        help="Path to project configuration YAML",
    )

    # forecast
    p_forecast = sub.add_parser("forecast", help="Display latest published forecast summary")
    p_forecast.add_argument(
        "--series",
        type=str,
        default=None,
        help="Filter forecast by series ID",
    )

    # report
    p_report = sub.add_parser("report", help="Print summary comparison and evaluation reports")
    p_report.add_argument(
        "--type",
        choices=["holdout", "validation", "monitoring"],
        default="holdout",
        help="Report type to view",
    )

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return run_doctor()
    if args.command == "ingest":
        return run_ingest(config_path=args.config, mode=args.mode, offline=args.offline)
    if args.command == "features":
        return run_features(config_path=args.config, target_series=args.target_series)
    if args.command == "splits":
        return run_splits(config_path=args.config, manifest_path=args.out)
    if args.command == "backtest":
        return run_backtest(
            config_path=args.config,
            models=args.models,
            split=args.split,
            target_series=args.target_series,
        )
    if args.command == "select":
        return run_select(config_path=args.config)
    if args.command == "holdout":
        return run_holdout(
            config_path=args.config,
            override_exploratory=args.override_exploratory,
            intervals_only=args.intervals_only,
        )
    if args.command == "pipeline":
        if args.pipeline_subcommand == "run":
            from palmguard.pipeline import execute_pipeline

            res = execute_pipeline(config_path=args.config, mode=args.mode, offline=args.offline)
            print(
                f"=== Pipeline execution complete: {res['status']} ({res['forecast_count']} forecasts published) ==="
            )
            return 0
    if args.command == "score":
        from palmguard.config import load_config
        from palmguard.features import build_monthly_panel_df
        from palmguard.pipeline import run_pipeline_score_step

        cfg = load_config(args.config)
        panel = build_monthly_panel_df(
            Path(cfg.paths.raw_dir), as_of=cfg.project.frozen_vintage_date
        )
        sc = run_pipeline_score_step(Path("."), cfg, panel)
        print(f"[*] Scored {len(sc)} forecasts against observed actuals.")
        return 0
    if args.command == "monitor":
        from palmguard.monitoring import run_monitoring_audit

        res = run_monitoring_audit(Path("."), config_path=args.config)
        print(
            f"[*] Monitoring audit complete for {len(res)} series. Output written to reports/published/monitoring.json"
        )
        return 0
    if args.command == "forecast":
        import json

        pub_file = Path("reports/published/forecast.json")
        if not pub_file.exists():
            print(
                f"[!] No published forecast found at {pub_file}. Run 'palmguard pipeline run' first."
            )
            return 1
        with open(pub_file, encoding="utf-8") as f:
            data = json.load(f)
        print(f"=== PalmGuard Published Forecasts (as of {data.get('published_at_utc')}) ===")
        print(f"Disclaimer: {data.get('disclaimer')}\n")
        for fc in data.get("forecasts", []):
            if args.series and fc.get("series_id") != args.series:
                continue
            print(
                f"[*] {fc['series_id']} | h={fc['horizon']} ({fc['target_month']}): {fc['y_pred']} "
                f"[80%: {fc['q80_lower']} - {fc['q80_upper']} | 90%: {fc['q90_lower']} - {fc['q90_upper']}]"
            )
        return 0
    if args.command == "report":
        if args.type == "holdout":
            p = Path("reports/forecast_comparison.md")
            if p.exists():
                print(p.read_text(encoding="utf-8"))
            else:
                print(f"[!] {p} not found.")
        elif args.type == "validation":
            p = Path("reports/validation_metrics.csv")
            if p.exists():
                print(p.read_text(encoding="utf-8"))
            else:
                print(f"[!] {p} not found.")
        elif args.type == "monitoring":
            p = Path("reports/published/monitoring.json")
            if p.exists():
                print(p.read_text(encoding="utf-8"))
            else:
                print(f"[!] {p} not found.")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
