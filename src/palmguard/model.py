"""LightGBM forecasting models M1 and M2 (Task T12).

Defines direct multi-horizon LightGBM regressors per 05_FORECAST_EXPERIMENT_PLAN.md:
- Target: ln(y[t+h] / y[t]) (monthly log return to horizon h). Forecast price: y[t] * exp(pred).
- M1: Lags only (own-series return lags, rolling statistics, distance from 12m high/low, calendar).
- M2: Lags plus drivers (M1 features + exogenous returns and rolling means respecting publication lags).
- Model architecture: Direct model per horizon h in {1, 2, 3}.
- Training cutoff: Training labels strictly respect fold origin cutoffs: for origin t and horizon h,
  the latest training origin is t - h so that no target observation from t or later is used.
- Tuning: Evaluates the fixed 8-configuration grid declared in config/project.yaml.
- Tracking: Logs parameter configurations and validation MASE runs to MLflow.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Any, Sequence

import lightgbm as lgb
import numpy as np
import pandas as pd

from palmguard.config import ProjectConfig
from palmguard.evaluation import calculate_mase, calculate_naive_scale
from palmguard.splits import OriginSplitInfo

logger = logging.getLogger(__name__)

M1_FEATURE_COLUMNS = [
    "return_lag1",
    "return_lag2",
    "return_lag3",
    "return_lag6",
    "return_lag12",
    "return_roll_mean_3m",
    "return_roll_std_3m",
    "return_roll_mean_6m",
    "return_roll_std_6m",
    "return_roll_mean_12m",
    "return_roll_std_12m",
    "pct_dist_from_12m_max",
    "pct_dist_from_12m_min",
    "origin_month_num",
    "origin_quarter",
]

M2_FEATURE_COLUMNS = M1_FEATURE_COLUMNS + [
    "driver_usdmyr_return_1m",
    "driver_usdmyr_roll_mean_3m",
    "driver_brent_return_1m",
    "driver_brent_roll_mean_3m",
    "driver_soyoil_return_1m",
    "driver_soyoil_roll_mean_3m",
    "driver_ppi_return_1m",
    "driver_ppi_roll_mean_3m",
    "driver_exports_return_1m",
    "driver_exports_roll_mean_3m",
]


@dataclass
class LgbmModelBundle:
    """Fitted LightGBM models for horizons 1, 2, 3."""

    model_id: str  # 'M1' or 'M2'
    series_id: str
    origin_month: str
    params: dict[str, Any]
    feature_columns: list[str]
    models: dict[int, lgb.LGBMRegressor]  # horizon -> fitted model


def get_feature_columns(model_id: str) -> list[str]:
    """Return declared feature set for M1 or M2."""
    if model_id == "M1":
        return list(M1_FEATURE_COLUMNS)
    if model_id == "M2":
        return list(M2_FEATURE_COLUMNS)
    raise ValueError(f"Unknown LightGBM model_id: {model_id}")


def generate_grid_configurations(cfg: ProjectConfig) -> list[dict[str, Any]]:
    """Expand the fixed Cartesian grid declared in project config (at most 8 configurations)."""
    grid_dict = cfg.modelling.lgbm.grid.model_dump()
    keys = list(grid_dict.keys())
    values = [grid_dict[k] for k in keys]
    configs: list[dict[str, Any]] = []
    for prod in itertools.product(*values):
        configs.append(dict(zip(keys, prod)))
    return configs


def fit_and_predict_lgbm_fold(
    features_df: pd.DataFrame,
    fold: OriginSplitInfo,
    model_id: str,
    params: dict[str, Any],
    horizons: Sequence[int] = (1, 2, 3),
    seed: int = 42,
) -> tuple[dict[int, float], dict[int, lgb.LGBMRegressor]]:
    """Fit direct LightGBM models per horizon for a single origin fold.

    Enforces label cutoff: for origin t and horizon h, the latest usable training
    row has origin <= t - h (meaning target <= t).
    """
    feature_cols = get_feature_columns(model_id)
    origin_m = fold.origin_month

    if origin_m not in features_df["origin_month"].values:
        raise ValueError(f"Origin {origin_m} not found in features DataFrame")

    origin_idx = features_df[features_df["origin_month"] == origin_m].index[0]
    origin_row = features_df.iloc[[origin_idx]]
    y_origin = float(origin_row["y_origin"].iloc[0])

    preds: dict[int, float] = {}
    fitted_models: dict[int, lgb.LGBMRegressor] = {}

    for h in horizons:
        # Cutoff: training rows strictly up to origin_idx - h
        train_end_idx = origin_idx - h
        if train_end_idx < 0:
            # Fallback if no history exists: predict return 0.0 (naive y_origin)
            preds[h] = y_origin
            continue

        train_df = features_df.iloc[: train_end_idx + 1]
        target_col = f"target_return_h{h}"

        # Drop any rows with NaN in features or target
        valid_mask = train_df[feature_cols + [target_col]].notna().all(axis=1)
        train_clean = train_df[valid_mask]

        if len(train_clean) < params.get("min_child_samples", 5):
            preds[h] = y_origin
            continue

        X_train = train_clean[feature_cols].values
        y_train = train_clean[target_col].values

        model = lgb.LGBMRegressor(
            n_estimators=params.get("n_estimators", 200),
            learning_rate=params["learning_rate"],
            num_leaves=params["num_leaves"],
            min_child_samples=params["min_child_samples"],
            random_state=seed,
            verbosity=-1,
            n_jobs=1,
        )
        model.fit(X_train, y_train)
        fitted_models[h] = model

        # Predict log return for current origin
        X_test = origin_row[feature_cols].values
        pred_return = float(model.predict(X_test)[0])
        # Convert predicted log return to price level: y_hat = y_origin * exp(pred_return)
        preds[h] = y_origin * float(np.exp(pred_return))

    return preds, fitted_models


def select_best_lgbm_params(
    features_df: pd.DataFrame,
    series_series: pd.Series,
    folds: list[OriginSplitInfo],
    model_id: str,
    grid_configs: list[dict[str, Any]],
    horizons: Sequence[int] = (1, 2, 3),
    seed: int = 42,
    log_to_mlflow: bool = True,
    tracking_uri: str | None = None,
) -> tuple[dict[str, Any], dict[str, float]]:
    """Select the LightGBM grid configuration with the lowest pooled validation MASE.

    Logs experiment runs and parameters to MLflow if enabled.
    """
    if log_to_mlflow and tracking_uri:
        import mlflow

        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(f"palmguard_{model_id}")

    best_params = grid_configs[0]
    best_mase = float("inf")
    all_scores: dict[str, float] = {}

    for config in grid_configs:
        config_name = f"leaves={config['num_leaves']}_child={config['min_child_samples']}_lr={config['learning_rate']}"
        all_actuals: list[float] = []
        all_preds: list[float] = []
        scales: list[float] = []

        for fold in folds:
            hist = series_series.loc[: fold.training_end_month].values
            scale = calculate_naive_scale(hist)
            preds, _ = fit_and_predict_lgbm_fold(
                features_df, fold, model_id=model_id, params=config, horizons=horizons, seed=seed
            )

            for h in horizons:
                t_m = fold.target_months.get(f"h{h}")
                if t_m in series_series.index:
                    all_actuals.append(float(series_series.loc[t_m]))
                    all_preds.append(preds[h])
                    scales.append(scale)

        mean_scale = float(np.mean(scales)) if scales else 1.0
        val_mase = calculate_mase(all_actuals, all_preds, scale=mean_scale)
        all_scores[config_name] = val_mase

        if log_to_mlflow and tracking_uri:
            import mlflow

            with mlflow.start_run(run_name=f"{model_id}_{config_name}"):
                mlflow.log_params(config)
                mlflow.log_param("model_id", model_id)
                mlflow.log_metric("val_mase", val_mase)

        if val_mase < best_mase:
            best_mase = val_mase
            best_params = config

    return best_params, all_scores


def backtest_lgbm(
    features_df: pd.DataFrame,
    series_id: str,
    folds: list[OriginSplitInfo],
    model_id: str,
    params: dict[str, Any],
    split_name: str = "validation",
    horizons: Sequence[int] = (1, 2, 3),
    seed: int = 42,
) -> tuple[pd.DataFrame, dict[str, LgbmModelBundle]]:
    """Execute rolling-origin backtest for LightGBM M1 or M2.

    Returns:
    - predictions_df with columns:
      [series_id, model, origin, target, horizon, actual, prediction, fit_failed, fallback_model, split]
    - bundles: map of origin_month -> LgbmModelBundle containing fitted models
    """
    records: list[dict[str, object]] = []
    bundles: dict[str, LgbmModelBundle] = {}

    for fold in folds:
        preds, fitted_models = fit_and_predict_lgbm_fold(
            features_df, fold, model_id=model_id, params=params, horizons=horizons, seed=seed
        )

        bundles[fold.origin_month] = LgbmModelBundle(
            model_id=model_id,
            series_id=series_id,
            origin_month=fold.origin_month,
            params=params,
            feature_columns=get_feature_columns(model_id),
            models=fitted_models,
        )

        orig_row = features_df[features_df["origin_month"] == fold.origin_month].iloc[0]

        for h in horizons:
            t_m = fold.target_months.get(f"h{h}")
            # Target actual from features table
            act_val = (
                float(orig_row[f"y_target_h{h}"])
                if pd.notna(orig_row.get(f"y_target_h{h}"))
                else None
            )

            records.append(
                {
                    "series_id": series_id,
                    "model": model_id,
                    "origin": fold.origin_month,
                    "target": t_m,
                    "horizon": h,
                    "actual": act_val,
                    "prediction": preds[h],
                    "fit_failed": False,
                    "fallback_model": None,
                    "split": split_name,
                }
            )

    df_out = pd.DataFrame(records)
    return df_out, bundles
