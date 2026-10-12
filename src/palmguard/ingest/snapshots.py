"""Immutable, content-addressed raw snapshot store and revision diff utilities."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

REVISION_COLUMNS = [
    "series_id",
    "period",
    "old_value",
    "new_value",
    "old_snapshot_id",
    "new_snapshot_id",
]


class SnapshotImmutabilityError(FileExistsError):
    """Raised when attempting to overwrite or reopen an existing snapshot path."""


class SnapshotValidationError(ValueError):
    """Raised when raw payload fails validation before snapshot storage."""


class SnapshotManifest(BaseModel):
    """Metadata recorded alongside every raw data snapshot (03_DATA_SPEC.md section 3)."""

    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    request_url: str = Field(min_length=1)
    resolved_url: str = Field(min_length=1)
    http_status: int = Field(ge=100, le=599)
    retrieved_at_utc: str = Field(min_length=10)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    schema_version: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    snapshot_id: str = Field(min_length=1)
    filename: str = Field(default="data.bin", min_length=1)


@dataclass(frozen=True)
class SnapshotWriteResult:
    """Outcome of a snapshot write operation."""

    manifest: SnapshotManifest
    status: Literal["written", "no_change"]
    snapshot_dir: Path
    payload_path: Path
    manifest_path: Path

    @property
    def changed(self) -> bool:
        return self.status == "written"


def compute_sha256(payload: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of raw bytes."""
    return hashlib.sha256(payload).hexdigest()


def build_snapshot_id(source: str, dataset: str, retrieved_date: str, sha256: str) -> str:
    """Format snapshot identifier `<source>.<dataset>.<date>.<sha256[:12]>`."""
    return f"{source}.{dataset}.{retrieved_date}.{sha256[:12]}"


def get_snapshot_dir(raw_root: Path, source: str, dataset: str, retrieved_date: str) -> Path:
    """Return `data/raw/<source>/<dataset>/retrieved=<YYYY-MM-DD>` directory path."""
    return raw_root / source / dataset / f"retrieved={retrieved_date}"


def list_snapshots(raw_root: Path, source: str, dataset: str) -> list[SnapshotManifest]:
    """Return all recorded SnapshotManifests for a source/dataset ordered by retrieval date."""
    dataset_dir = raw_root / source / dataset
    if not dataset_dir.is_dir():
        return []
    manifests: list[SnapshotManifest] = []
    for entry in sorted(dataset_dir.iterdir(), key=lambda p: p.name):
        if entry.is_dir() and entry.name.startswith("retrieved="):
            manifest_file = entry / "manifest.json"
            if manifest_file.is_file():
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                manifests.append(SnapshotManifest.model_validate(data))
    return manifests


def latest_snapshot(raw_root: Path, source: str, dataset: str) -> SnapshotManifest | None:
    """Return the most recent SnapshotManifest for a source/dataset, or None if none exist."""
    snapshots = list_snapshots(raw_root, source, dataset)
    return snapshots[-1] if snapshots else None


def _date_from_snapshot_id(manifest: SnapshotManifest) -> str:
    parts = manifest.snapshot_id.split(".")
    if len(parts) >= 4:
        return parts[2]
    return manifest.retrieved_at_utc[:10]


def write_snapshot(
    raw_root: Path,
    *,
    source: str,
    dataset: str,
    payload: bytes,
    filename: str,
    request_url: str,
    resolved_url: str | None = None,
    http_status: int = 200,
    retrieved_at_utc: str | None = None,
    retrieved_date: str | None = None,
    schema_version: str = "1.0",
    row_count: int | None = None,
    validator: Callable[[bytes], int] | None = None,
) -> SnapshotWriteResult:
    """Validate and store an immutable raw snapshot if content changed since latest snapshot."""
    if validator is not None:
        try:
            validated_rows = validator(payload)
        except SnapshotValidationError:
            raise
        except Exception as exc:
            raise SnapshotValidationError(f"Payload failed contract validation: {exc}") from exc
        if row_count is None:
            row_count = validated_rows

    effective_rows = 0 if row_count is None else int(row_count)
    if effective_rows < 0:
        raise SnapshotValidationError("row_count must be non-negative")

    sha256 = compute_sha256(payload)
    ts_utc = retrieved_at_utc or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    date_str = retrieved_date or ts_utc[:10]

    latest = latest_snapshot(raw_root, source, dataset)
    if latest is not None and latest.sha256 == sha256:
        logger.info("no change: %s/%s (%s)", source, dataset, latest.snapshot_id)
        existing_date = _date_from_snapshot_id(latest)
        existing_dir = get_snapshot_dir(raw_root, source, dataset, existing_date)
        return SnapshotWriteResult(
            manifest=latest,
            status="no_change",
            snapshot_dir=existing_dir,
            payload_path=existing_dir / latest.filename,
            manifest_path=existing_dir / "manifest.json",
        )

    target_dir = get_snapshot_dir(raw_root, source, dataset, date_str)
    payload_path = target_dir / filename
    manifest_path = target_dir / "manifest.json"

    if (
        payload_path.exists()
        or manifest_path.exists()
        or (target_dir.exists() and any(target_dir.iterdir()))
    ):
        raise SnapshotImmutabilityError(
            f"Existing snapshot path is immutable and cannot be rewritten: {target_dir}"
        )

    snapshot_id = build_snapshot_id(source, dataset, date_str, sha256)
    manifest = SnapshotManifest(
        source=source,
        dataset=dataset,
        request_url=request_url,
        resolved_url=resolved_url or request_url,
        http_status=http_status,
        retrieved_at_utc=ts_utc,
        sha256=sha256,
        bytes=len(payload),
        schema_version=schema_version,
        row_count=effective_rows,
        snapshot_id=snapshot_id,
        filename=filename,
    )

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        with payload_path.open("xb") as f_payload:
            f_payload.write(payload)
        with manifest_path.open("x", encoding="utf-8") as f_manifest:
            f_manifest.write(json.dumps(manifest.model_dump(), indent=2) + "\n")
    except FileExistsError as exc:
        raise SnapshotImmutabilityError(
            f"Existing snapshot file cannot be reopened for writing: {target_dir}"
        ) from exc

    return SnapshotWriteResult(
        manifest=manifest,
        status="written",
        snapshot_dir=target_dir,
        payload_path=payload_path,
        manifest_path=manifest_path,
    )


def _empty_revisions_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "series_id": pd.Series(dtype="string"),
            "period": pd.Series(dtype="string"),
            "old_value": pd.Series(dtype="float64"),
            "new_value": pd.Series(dtype="float64"),
            "old_snapshot_id": pd.Series(dtype="string"),
            "new_snapshot_id": pd.Series(dtype="string"),
        }
    )


def diff_revisions(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    *,
    old_snapshot_id: str,
    new_snapshot_id: str,
    series_col: str = "series_id",
    period_col: str = "month",
    value_col: str = "value",
    atol: float = 1e-9,
    rtol: float = 1e-9,
) -> pd.DataFrame:
    """Compute value revisions for overlapping (series, period) pairs between two snapshots."""
    if old_df.empty or new_df.empty:
        return _empty_revisions_df()

    left = old_df[[series_col, period_col, value_col]].copy()
    right = new_df[[series_col, period_col, value_col]].copy()
    left[period_col] = left[period_col].astype(str)
    right[period_col] = right[period_col].astype(str)

    merged = left.merge(
        right,
        on=[series_col, period_col],
        how="inner",
        suffixes=("_old", "_new"),
    )
    if merged.empty:
        return _empty_revisions_df()

    old_vals = merged[f"{value_col}_old"].to_numpy(dtype=float)
    new_vals = merged[f"{value_col}_new"].to_numpy(dtype=float)
    changed_mask = ~np.isclose(old_vals, new_vals, atol=atol, rtol=rtol, equal_nan=True)
    changed = merged.loc[changed_mask].sort_values([series_col, period_col]).reset_index(drop=True)
    if changed.empty:
        return _empty_revisions_df()

    return pd.DataFrame(
        {
            "series_id": changed[series_col].astype(str),
            "period": changed[period_col].astype(str),
            "old_value": changed[f"{value_col}_old"].astype(float),
            "new_value": changed[f"{value_col}_new"].astype(float),
            "old_snapshot_id": old_snapshot_id,
            "new_snapshot_id": new_snapshot_id,
        }
    )


def append_revisions(revisions_path: Path, new_revisions: pd.DataFrame) -> pd.DataFrame:
    """Append newly detected revisions to `revisions.parquet` without duplicating entries."""
    existing = (
        pd.read_parquet(revisions_path) if revisions_path.is_file() else _empty_revisions_df()
    )
    if new_revisions.empty:
        if not revisions_path.is_file():
            revisions_path.parent.mkdir(parents=True, exist_ok=True)
            existing.to_parquet(revisions_path, index=False)
        return existing

    if existing.empty:
        combined = new_revisions[REVISION_COLUMNS].copy()
    else:
        combined = pd.concat(
            [existing[REVISION_COLUMNS], new_revisions[REVISION_COLUMNS]], ignore_index=True
        )

    combined = (
        combined.drop_duplicates(
            subset=["series_id", "period", "old_snapshot_id", "new_snapshot_id"],
            keep="first",
        )
        .sort_values(["series_id", "period", "new_snapshot_id"])
        .reset_index(drop=True)
    )
    revisions_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(revisions_path, index=False)
    return combined
