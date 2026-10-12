"""Tests for the immutable snapshot store and revision diffing (Task T02)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import pytest

from palmguard.ingest.snapshots import (
    SnapshotImmutabilityError,
    SnapshotValidationError,
    append_revisions,
    build_snapshot_id,
    compute_sha256,
    diff_revisions,
    latest_snapshot,
    list_snapshots,
    write_snapshot,
)


def test_identical_payload_twice_writes_one_snapshot(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = b"month,value\n2026-08-01,105.2\n2026-09-01,106.4\n"

    res1 = write_snapshot(
        tmp_path,
        source="dosm",
        dataset="ppi_sitc",
        payload=payload,
        filename="ppi_sitc.csv",
        request_url="https://storage.dosm.gov.my/ppi/ppi_sitc.csv",
        retrieved_at_utc="2026-10-11T08:00:00+00:00",
        row_count=2,
    )
    assert res1.status == "written"
    assert res1.changed is True
    assert res1.payload_path.read_bytes() == payload
    assert res1.manifest_path.is_file()

    expected_sha = compute_sha256(payload)
    assert res1.manifest.sha256 == expected_sha
    assert res1.manifest.bytes == len(payload)
    assert res1.manifest.row_count == 2
    assert res1.manifest.snapshot_id == build_snapshot_id(
        "dosm", "ppi_sitc", "2026-10-11", expected_sha
    )

    raw_manifest = json.loads(res1.manifest_path.read_text(encoding="utf-8"))
    for key in (
        "source",
        "dataset",
        "request_url",
        "resolved_url",
        "http_status",
        "retrieved_at_utc",
        "sha256",
        "bytes",
        "schema_version",
        "row_count",
        "snapshot_id",
    ):
        assert key in raw_manifest

    # Second call with identical payload on a later date must write nothing and log "no change"
    with caplog.at_level(logging.INFO):
        res2 = write_snapshot(
            tmp_path,
            source="dosm",
            dataset="ppi_sitc",
            payload=payload,
            filename="ppi_sitc.csv",
            request_url="https://storage.dosm.gov.my/ppi/ppi_sitc.csv",
            retrieved_at_utc="2026-10-12T08:00:00+00:00",
            row_count=2,
        )

    assert res2.status == "no_change"
    assert res2.changed is False
    assert res2.manifest.snapshot_id == res1.manifest.snapshot_id
    assert "no change" in caplog.text
    assert len(list_snapshots(tmp_path, "dosm", "ppi_sitc")) == 1


def test_existing_snapshot_is_never_rewritten(tmp_path: Path) -> None:
    payload_v1 = b"month,value\n2026-08-01,105.2\n"
    payload_v2 = b"month,value\n2026-08-01,109.9\n"

    res1 = write_snapshot(
        tmp_path,
        source="dosm",
        dataset="ppi_sitc",
        payload=payload_v1,
        filename="ppi_sitc.csv",
        request_url="https://storage.dosm.gov.my/ppi/ppi_sitc.csv",
        retrieved_at_utc="2026-10-11T08:00:00+00:00",
        row_count=1,
    )
    original_manifest_text = res1.manifest_path.read_text(encoding="utf-8")

    # Attempting to write different content to the same retrieved date must raise
    with pytest.raises(SnapshotImmutabilityError):
        write_snapshot(
            tmp_path,
            source="dosm",
            dataset="ppi_sitc",
            payload=payload_v2,
            filename="ppi_sitc.csv",
            request_url="https://storage.dosm.gov.my/ppi/ppi_sitc.csv",
            retrieved_at_utc="2026-10-11T18:30:00+00:00",
            row_count=1,
        )

    # Original files must be completely untouched
    assert res1.payload_path.read_bytes() == payload_v1
    assert res1.manifest_path.read_text(encoding="utf-8") == original_manifest_text


def test_validator_failure_prevents_snapshot_write(tmp_path: Path) -> None:
    def reject_bad_payload(data: bytes) -> int:
        if b"bad" in data:
            raise ValueError("corrupted schema")
        return 1

    with pytest.raises(SnapshotValidationError, match="corrupted schema"):
        write_snapshot(
            tmp_path,
            source="worldbank",
            dataset="pink_sheet",
            payload=b"bad,bytes",
            filename="CMO.xlsx",
            request_url="https://www.worldbank.org/CMO.xlsx",
            retrieved_at_utc="2026-10-11T08:00:00+00:00",
            validator=reject_bad_payload,
        )

    assert latest_snapshot(tmp_path, "worldbank", "pink_sheet") is None
    assert not (tmp_path / "worldbank").exists()


def test_new_snapshot_on_later_date_and_revision_diff(tmp_path: Path) -> None:
    df_v1 = pd.DataFrame(
        {
            "series_id": ["ppi_oilsfats_my", "ppi_oilsfats_my"],
            "month": ["2026-07-01", "2026-08-01"],
            "value": [140.0, 142.5],
        }
    )
    df_v2 = pd.DataFrame(
        {
            "series_id": ["ppi_oilsfats_my", "ppi_oilsfats_my", "ppi_oilsfats_my"],
            "month": ["2026-07-01", "2026-08-01", "2026-09-01"],
            "value": [140.0, 143.1, 144.0],
        }
    )

    s1 = write_snapshot(
        tmp_path,
        source="dosm",
        dataset="ppi_sitc",
        payload=df_v1.to_csv(index=False).encode("utf-8"),
        filename="ppi_sitc.csv",
        request_url="https://storage.dosm.gov.my/ppi/ppi_sitc.csv",
        retrieved_at_utc="2026-09-28T08:00:00+00:00",
        row_count=len(df_v1),
    )
    s2 = write_snapshot(
        tmp_path,
        source="dosm",
        dataset="ppi_sitc",
        payload=df_v2.to_csv(index=False).encode("utf-8"),
        filename="ppi_sitc.csv",
        request_url="https://storage.dosm.gov.my/ppi/ppi_sitc.csv",
        retrieved_at_utc="2026-10-28T08:00:00+00:00",
        row_count=len(df_v2),
    )

    snaps = list_snapshots(tmp_path, "dosm", "ppi_sitc")
    assert len(snaps) == 2
    assert latest_snapshot(tmp_path, "dosm", "ppi_sitc") == s2.manifest

    revs = diff_revisions(
        df_v1,
        df_v2,
        old_snapshot_id=s1.manifest.snapshot_id,
        new_snapshot_id=s2.manifest.snapshot_id,
    )
    assert len(revs) == 1
    row = revs.iloc[0]
    assert row["series_id"] == "ppi_oilsfats_my"
    assert row["period"] == "2026-08-01"
    assert row["old_value"] == pytest.approx(142.5)
    assert row["new_value"] == pytest.approx(143.1)

    revisions_file = tmp_path / "processed" / "revisions.parquet"
    stored1 = append_revisions(revisions_file, revs)
    stored2 = append_revisions(revisions_file, revs)
    assert len(stored1) == 1
    assert len(stored2) == 1
