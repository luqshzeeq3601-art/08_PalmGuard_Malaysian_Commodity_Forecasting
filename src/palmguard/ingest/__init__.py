"""Ingestion package for raw snapshots and source connectors."""

from palmguard.ingest.snapshots import (
    SnapshotImmutabilityError,
    SnapshotManifest,
    SnapshotValidationError,
    SnapshotWriteResult,
    append_revisions,
    build_snapshot_id,
    compute_sha256,
    diff_revisions,
    get_snapshot_dir,
    latest_snapshot,
    list_snapshots,
    write_snapshot,
)

__all__ = [
    "SnapshotImmutabilityError",
    "SnapshotManifest",
    "SnapshotValidationError",
    "SnapshotWriteResult",
    "append_revisions",
    "build_snapshot_id",
    "compute_sha256",
    "diff_revisions",
    "get_snapshot_dir",
    "latest_snapshot",
    "list_snapshots",
    "write_snapshot",
]
