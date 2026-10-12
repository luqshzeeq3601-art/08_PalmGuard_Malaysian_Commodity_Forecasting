"""Typed project configuration loader for config/project.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ProjectMetadataConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    seed: int = 42
    origin_day_of_month: int = Field(ge=1, le=28)
    primary_target: str
    secondary_target: str
    frozen_vintage_date: str


class PathsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_dir: str = "data/raw"
    processed_dir: str = "data/processed"
    artifacts_dir: str = "artifacts/champion"
    reports_dir: str = "reports"
    published_dir: str = "reports/published"
    queries_dir: str = "queries"
    mlflow_tracking_uri: str = "sqlite:///mlflow.db"


class DefinitionBreak(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])-01$")
    basis: str = Field(min_length=1)


class TargetConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    series_id: str
    display_name: str
    short_description: str
    unit: str
    min_history_months: int = Field(ge=1)
    min_training_months: int = Field(ge=12)
    validation_origins: int = Field(ge=1)
    holdout_origins: int = Field(ge=1)
    definition_breaks: list[DefinitionBreak] = Field(default_factory=list)


class LgbmGridConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    num_leaves: list[int]
    min_child_samples: list[int]
    learning_rate: list[float]


class LgbmConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    n_estimators: int = Field(ge=1)
    objective: str = "regression"
    grid: LgbmGridConfig


class SelectionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    relative_mase_tie_threshold: float = Field(ge=0.0)
    simplicity_order: list[str]


class ObjectivesConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    o2_h1_mase_max: float = Field(gt=0.0)
    o3_coverage_tolerance: float = Field(gt=0.0, lt=1.0)


class ModellingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    seed: int = 42
    arima_orders: list[list[int]]
    lgbm: LgbmConfig
    selection: SelectionConfig
    objectives: ObjectivesConfig


class ConformalConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    levels: list[float]
    window_size: int = Field(ge=5)
    aci_gamma: float = Field(gt=0.0, lt=1.0)


class MonitoringConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    rolling_windows_months: list[int]
    drift_recent_months: int = Field(ge=6)
    psi_threshold: float = Field(gt=0.0)
    ks_alpha: float = Field(gt=0.0, lt=1.0)


class AttributionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    licence: str
    sources: list[str]
    transformation_note: str
    disclaimer: str


class ProjectConfig(BaseModel):
    """Top-level configuration loaded from `config/project.yaml`."""

    model_config = ConfigDict(frozen=True)

    project: ProjectMetadataConfig
    paths: PathsConfig
    publication_lags: dict[str, int]
    publication_schedule: dict[str, str]
    horizons: list[int]
    targets: dict[str, TargetConfig]
    modelling: ModellingConfig
    conformal: ConformalConfig
    monitoring: MonitoringConfig
    attribution: AttributionConfig


def load_config(path: Path | str = Path("config/project.yaml")) -> ProjectConfig:
    """Load and validate `config/project.yaml`."""
    cfg_path = Path(path)
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {cfg_path}")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg = ProjectConfig.model_validate(raw)
    for series_id, lag in cfg.publication_lags.items():
        if lag < 1:
            raise ValueError(f"Publication lag for {series_id} must be >= 1, got {lag}")
    return cfg
