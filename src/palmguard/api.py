"""PalmGuard FastAPI service (Task T20).

Exposes 5 typed endpoints:
- GET /health: Liveness check
- GET /ready: Readiness check returning model version, vintage, and loaded artifact status
- GET /forecast: Filterable forecast records with intervals, bounds, units, and disclaimer
- GET /history: Historical forecasts, errors, and interval hit status
- GET /monitoring: Rolling errors, empirical coverage, and feature drift status
All responses are typed via Pydantic models and read strictly from reports/published/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict

app = FastAPI(
    title="PalmGuard Malaysian Commodity Forecasting API",
    version="0.1.0",
    description="Official REST API for PalmGuard commodity price and index forecasting.",
)

PUBLISHED_DIR = Path("reports/published")
ARTIFACTS_DIR = Path("artifacts/champion")


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    project_name: str
    version: str
    frozen_vintage_date: str
    champions: dict[str, str]
    artifacts_loaded: bool


class SingleForecastItem(BaseModel):
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


class ForecastResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str
    version: str
    published_at_utc: str
    disclaimer: str
    forecasts: list[SingleForecastItem]


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    series_id: str
    origin_month: str
    target_month: str
    horizon: int
    y_pred: float
    y_actual: float | None = None
    abs_error: float | None = None
    abs_pct_error: float | None = None
    interval_hit_80: int | None = None
    interval_hit_90: int | None = None


class HistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int
    history: list[dict[str, Any]]


def _load_published_forecast() -> dict[str, Any]:
    fpath = PUBLISHED_DIR / "forecast.json"
    if not fpath.exists():
        raise HTTPException(status_code=503, detail="Forecast artifact not yet published")
    with open(fpath, encoding="utf-8") as f:
        return json.load(f)


def _load_published_monitoring() -> dict[str, Any]:
    mpath = PUBLISHED_DIR / "monitoring.json"
    if not mpath.exists():
        raise HTTPException(status_code=503, detail="Monitoring artifact not yet published")
    with open(mpath, encoding="utf-8") as f:
        return json.load(f)


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Liveness probe: returns 200 if process is alive."""
    return HealthResponse(status="alive")


@app.get("/ready", response_model=ReadyResponse)
def get_ready() -> ReadyResponse:
    """Readiness probe: returns 200 if published artifacts exist and metadata is loaded."""
    meta_path = ARTIFACTS_DIR / "metadata.json"
    forecast_path = PUBLISHED_DIR / "forecast.json"

    if not meta_path.exists() or not forecast_path.exists():
        raise HTTPException(status_code=503, detail="Service not ready: artifacts missing")

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    return ReadyResponse(
        status="ready",
        project_name=meta.get("project_name", "PalmGuard"),
        version=meta.get("version", "0.1.0"),
        frozen_vintage_date=meta.get("frozen_vintage_date", "unknown"),
        champions=meta.get("selected_champions", {}),
        artifacts_loaded=True,
    )


@app.get("/forecast", response_model=ForecastResponse)
def get_forecast(
    series: str | None = Query(None, description="Optional filter by series_id"),
    horizon: int | None = Query(
        None, ge=1, le=3, description="Optional filter by horizon (1, 2, 3)"
    ),
) -> ForecastResponse:
    """Get latest published forecasts with intervals, bounds, and disclaimer."""
    data = _load_published_forecast()
    fcs = data.get("forecasts", [])

    if series:
        fcs = [f for f in fcs if f.get("series_id") == series]
    if horizon:
        fcs = [f for f in fcs if f.get("horizon") == horizon]

    if not fcs and (series or horizon):
        raise HTTPException(status_code=404, detail="No forecasts found matching criteria")

    return ForecastResponse(
        project=data.get("project", "PalmGuard"),
        version=data.get("version", "0.1.0"),
        published_at_utc=data.get("published_at_utc", ""),
        disclaimer=data.get("disclaimer", ""),
        forecasts=[SingleForecastItem(**f) for f in fcs],
    )


@app.get("/history", response_model=HistoryResponse)
def get_history(
    series: str | None = Query(None, description="Optional filter by series_id"),
    limit: int = Query(50, ge=1, le=1000, description="Max history records to return"),
) -> HistoryResponse:
    """Get historical forecasts, realized actuals, errors, and interval hit records."""
    hpath = PUBLISHED_DIR / "history.parquet"
    if not hpath.exists():
        return HistoryResponse(count=0, history=[])

    df = pd.read_parquet(hpath)
    if series and "series_id" in df.columns:
        df = df[df["series_id"] == series]

    df_subset = df.tail(limit)
    records = df_subset.to_dict(orient="records")
    return HistoryResponse(count=len(records), history=records)


@app.get("/monitoring")
def get_monitoring(
    series: str | None = Query(None, description="Optional filter by series_id"),
) -> dict[str, Any]:
    """Get rolling errors, coverage metrics, and drift statuses."""
    mon_data = _load_published_monitoring()
    if series:
        if series not in mon_data:
            raise HTTPException(
                status_code=404, detail=f"Series {series} not found in monitoring report"
            )
        return {series: mon_data[series]}
    return mon_data
