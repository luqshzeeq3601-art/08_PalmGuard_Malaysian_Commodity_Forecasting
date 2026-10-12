"""Split manifest and partition logic for rolling-origin evaluation (Task T09).

Enforces:
- Rolling origins with expanding training windows.
- Strict embargo buffer preventing validation target months from falling inside the holdout range.
- Minimum training months assertions (120 for palm_wb_myr, 96 for ppi_oilsfats_my).
- SHA-256 series panel hashing and frozen manifest schema for Gate G2.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from palmguard.config import ProjectConfig, TargetConfig
from palmguard.features import build_monthly_panel_df

DEFAULT_MANIFEST_PATH = Path("data/processed/split_manifest.json")


class OriginSplitInfo(BaseModel):
    """Origin specification and target month mapping for a fold."""

    model_config = ConfigDict(extra="forbid")

    origin_index: int = Field(..., ge=0)
    origin_month: str = Field(..., pattern=r"^\d{4}-\d{2}-01$")
    training_start_month: str = Field(..., pattern=r"^\d{4}-\d{2}-01$")
    training_end_month: str = Field(..., pattern=r"^\d{4}-\d{2}-01$")
    training_months_count: int = Field(..., ge=1)
    target_months: dict[str, str] = Field(
        ...,
        description="Map of horizon ('h1', 'h2', 'h3') to target month ('YYYY-MM-01')",
    )
    targets_observed: dict[str, bool] = Field(
        ...,
        description="Whether the target month exists in the frozen series history",
    )


class SeriesSplitManifest(BaseModel):
    """Frozen rolling-origin validation and holdout splits for a specific target series."""

    model_config = ConfigDict(extra="forbid")

    series_id: str
    display_name: str
    series_sha256: str
    total_months_count: int = Field(..., ge=1)
    min_series_month: str = Field(..., pattern=r"^\d{4}-\d{2}-01$")
    max_series_month: str = Field(..., pattern=r"^\d{4}-\d{2}-01$")
    min_training_months_required: int = Field(..., ge=1)
    validation_origins_count: int = Field(..., ge=1)
    holdout_origins_count: int = Field(..., ge=1)
    embargo_months: int = Field(..., ge=0)
    validation_origins_range: list[str] = Field(..., min_length=2, max_length=2)
    validation_targets_range: list[str] = Field(..., min_length=2, max_length=2)
    holdout_origins_range: list[str] = Field(..., min_length=2, max_length=2)
    holdout_targets_range: list[str] = Field(..., min_length=2, max_length=2)
    validation_folds: list[OriginSplitInfo]
    holdout_folds: list[OriginSplitInfo]


class FullSplitManifest(BaseModel):
    """Project-wide split manifest container frozen prior to model fitting (Gate G2)."""

    model_config = ConfigDict(extra="forbid")

    project_name: str
    version: str
    frozen_vintage_date: str
    generated_at_utc: str
    horizons: list[int]
    series: dict[str, SeriesSplitManifest]


def compute_series_hash(series_df: pd.DataFrame) -> str:
    """Compute deterministic SHA-256 over canonical (month, value) pairs."""
    sorted_df = series_df.sort_values("month").reset_index(drop=True)
    h = hashlib.sha256()
    for _, row in sorted_df.iterrows():
        entry = f"{row['month']}:{float(row['value']):.6f}\n"
        h.update(entry.encode("utf-8"))
    return h.hexdigest()


def _add_months_str(month_str: str, n: int) -> str:
    """Add n calendar months to a 'YYYY-MM-01' string."""
    dt = pd.to_datetime(month_str)
    res = dt + pd.DateOffset(months=n)
    return res.strftime("%Y-%m-%d")


def build_series_split(
    panel_df: pd.DataFrame,
    target_cfg: TargetConfig,
    horizons: list[int] | None = None,
) -> SeriesSplitManifest:
    """Build and validate rolling-origin splits for a designated target series.

    Embargo rule:
    Holdout origins are the final `holdout_origins` months of the series.
    To ensure no validation target month falls inside the holdout range (origins or targets),
    validation origins terminate `max(horizons)` months prior to the first holdout origin.
    """
    if horizons is None:
        horizons = [1, 2, 3]
    max_h = max(horizons)

    series_df = (
        panel_df[panel_df["series_id"] == target_cfg.series_id]
        .sort_values("month")
        .reset_index(drop=True)
    )
    if series_df.empty:
        raise ValueError(f"No rows in panel for series {target_cfg.series_id}")

    months = series_df["month"].tolist()
    total_months = len(months)
    series_hash = compute_series_hash(series_df)

    n_val = target_cfg.validation_origins
    n_hold = target_cfg.holdout_origins
    min_train = target_cfg.min_training_months

    # Holdout origins: final n_hold months
    holdout_origin_months = months[-n_hold:]
    first_holdout_origin = holdout_origin_months[0]
    first_holdout_idx = months.index(first_holdout_origin)

    # Validation origins: terminate with embargo so that no validation target reaches holdout targets.
    # For any validation origin v and h in horizons (up to max_h):
    # target month v + max_h must be < first_holdout_origin + 1 month.
    # Therefore, v + max_h <= first_holdout_origin.
    # The latest validation origin is first_holdout_idx - max_h.
    embargo_months = max_h
    val_end_idx = first_holdout_idx - embargo_months
    val_start_idx = val_end_idx - n_val + 1

    if val_start_idx < 0:
        raise ValueError(
            f"Series {target_cfg.series_id} has {total_months} months, insufficient for "
            f"embargo {embargo_months} and {n_val} validation origins."
        )

    val_origin_months = months[val_start_idx : val_end_idx + 1]
    if len(val_origin_months) != n_val:
        raise ValueError(f"Expected {n_val} validation origins, got {len(val_origin_months)}")

    # Check minimum training months for the very first validation origin
    first_val_train_count = val_start_idx + 1
    if first_val_train_count < min_train:
        raise ValueError(
            f"Series {target_cfg.series_id}: first validation origin has {first_val_train_count} "
            f"training months, failing minimum requirement of {min_train}."
        )

    # Build validation folds
    val_folds: list[OriginSplitInfo] = []
    val_all_targets: set[str] = set()
    for idx, orig_m in enumerate(val_origin_months):
        orig_pos = months.index(orig_m)
        target_map: dict[str, str] = {}
        observed_map: dict[str, bool] = {}
        for h in horizons:
            t_m = _add_months_str(orig_m, h)
            target_map[f"h{h}"] = t_m
            observed_map[f"h{h}"] = t_m in months
            val_all_targets.add(t_m)

        val_folds.append(
            OriginSplitInfo(
                origin_index=idx,
                origin_month=orig_m,
                training_start_month=months[0],
                training_end_month=orig_m,
                training_months_count=orig_pos + 1,
                target_months=target_map,
                targets_observed=observed_map,
            )
        )

    # Build holdout folds
    hold_folds: list[OriginSplitInfo] = []
    hold_all_targets: set[str] = set()
    for idx, orig_m in enumerate(holdout_origin_months):
        orig_pos = months.index(orig_m)
        target_map = {}
        observed_map = {}
        for h in horizons:
            t_m = _add_months_str(orig_m, h)
            target_map[f"h{h}"] = t_m
            observed_map[f"h{h}"] = t_m in months
            hold_all_targets.add(t_m)

        hold_folds.append(
            OriginSplitInfo(
                origin_index=idx,
                origin_month=orig_m,
                training_start_month=months[0],
                training_end_month=orig_m,
                training_months_count=orig_pos + 1,
                target_months=target_map,
                targets_observed=observed_map,
            )
        )

    # Core assertion: No validation target month may fall inside the holdout target range
    # (03_DATA_SPEC.md section 7 & todo.md T09)
    overlap = val_all_targets.intersection(hold_all_targets)
    if overlap:
        raise ValueError(
            f"Series {target_cfg.series_id}: Validation targets overlap holdout targets: {overlap}!"
        )

    if max(val_all_targets) >= min(hold_all_targets):
        raise ValueError(
            f"Series {target_cfg.series_id}: Max validation target {max(val_all_targets)} "
            f"is not strictly before min holdout target {min(hold_all_targets)}!"
        )

    return SeriesSplitManifest(
        series_id=target_cfg.series_id,
        display_name=target_cfg.display_name,
        series_sha256=series_hash,
        total_months_count=total_months,
        min_series_month=months[0],
        max_series_month=months[-1],
        min_training_months_required=min_train,
        validation_origins_count=n_val,
        holdout_origins_count=n_hold,
        embargo_months=embargo_months,
        validation_origins_range=[val_origin_months[0], val_origin_months[-1]],
        validation_targets_range=[min(val_all_targets), max(val_all_targets)],
        holdout_origins_range=[holdout_origin_months[0], holdout_origin_months[-1]],
        holdout_targets_range=[min(hold_all_targets), max(hold_all_targets)],
        validation_folds=val_folds,
        holdout_folds=hold_folds,
    )


def generate_split_manifest(
    cfg: ProjectConfig,
    panel_df: pd.DataFrame,
    *,
    generated_at_utc: str | None = None,
) -> FullSplitManifest:
    """Generate the full project split manifest across all declared targets."""
    if generated_at_utc is None:
        import datetime

        generated_at_utc = (
            datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        )

    series_manifests: dict[str, SeriesSplitManifest] = {}
    for target_key, target_cfg in cfg.targets.items():
        s_manifest = build_series_split(panel_df, target_cfg, horizons=cfg.horizons)
        series_manifests[target_key] = s_manifest

    return FullSplitManifest(
        project_name=cfg.project.name,
        version=cfg.project.version,
        frozen_vintage_date=cfg.project.frozen_vintage_date,
        generated_at_utc=generated_at_utc,
        horizons=cfg.horizons,
        series=series_manifests,
    )


def write_split_manifest(
    manifest: FullSplitManifest,
    out_path: Path = DEFAULT_MANIFEST_PATH,
) -> Path:
    """Write split manifest JSON to disk with 2-space indentation."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = manifest.model_dump_json(indent=2)
    out_path.write_text(content, encoding="utf-8")
    return out_path


def load_split_manifest(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> FullSplitManifest:
    """Load and validate an existing split manifest from disk."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Split manifest not found: {manifest_path}")
    raw_text = manifest_path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    return FullSplitManifest.model_validate(data)


def run_split_gate(
    cfg: ProjectConfig,
    root: Path = Path("."),
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> tuple[bool, FullSplitManifest]:
    """Execute Gate G2 verification and write frozen manifest."""
    raw_root = root / cfg.paths.raw_dir
    panel_df = build_monthly_panel_df(raw_root, as_of=cfg.project.frozen_vintage_date)
    target_manifest_path = manifest_path if manifest_path.is_absolute() else root / manifest_path

    manifest = generate_split_manifest(cfg, panel_df)
    write_split_manifest(manifest, target_manifest_path)

    # Re-read and re-validate from disk
    loaded = load_split_manifest(target_manifest_path)
    assert loaded.project_name == cfg.project.name
    assert set(loaded.series.keys()) == set(cfg.targets.keys())

    return True, loaded
