"""Tests for data contracts, config lag verification, revision logging, and Gate G1 (Task T06)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from palmguard.config import load_config
from palmguard.contracts import (
    MonthlyPanelRow,
    check_monthly_continuity,
    run_data_quality_gate,
    sync_revisions_from_snapshots,
    validate_monthly_series_df,
)
from palmguard.ingest.datagovmy import validate_dataset_payload
from palmguard.ingest.snapshots import (
    SnapshotValidationError,
    latest_snapshot,
    write_snapshot,
)


def test_config_loads_and_matches_data_spec_lags() -> None:
    cfg = load_config(Path("config/project.yaml"))
    assert cfg.publication_lags == {
        "palm_wb_usd": 1,
        "palm_wb_myr": 1,
        "brent_wb_usd": 1,
        "soyoil_wb_usd": 1,
        "usdmyr_avg": 1,
        "ppi_oilsfats_my": 2,
        "exports_sitc4": 3,
    }
    assert cfg.horizons == [1, 2, 3]
    assert cfg.targets["palm_wb_myr"].min_history_months == 180
    assert cfg.targets["ppi_oilsfats_my"].min_history_months == 200


def test_monthly_panel_row_and_series_contract_checks() -> None:
    row = MonthlyPanelRow(
        series_id="palm_wb_myr",
        month="2026-08-01",
        value=4250.5,
        available_from="2026-10-11",
        snapshot_id="wb+fx",
        is_provisional=False,
    )
    assert row.value == 4250.5

    with pytest.raises(ValueError):
        MonthlyPanelRow(
            series_id="unknown_series",
            month="2026-08-01",
            value=100.0,
            available_from="2026-10-11",
            snapshot_id="s1",
        )

    df_valid = pd.DataFrame(
        {
            "series_id": ["palm_wb_myr", "palm_wb_myr", "palm_wb_myr"],
            "month": ["2026-07-01", "2026-08-01", "2026-09-01"],
            "value": [4100.0, 4200.0, 4300.0],
            "available_from": ["2026-10-11"] * 3,
            "snapshot_id": ["snap.1"] * 3,
            "is_provisional": [False] * 3,
        }
    )
    summary = validate_monthly_series_df(df_valid, expected_series_id="palm_wb_myr", min_rows=3)
    assert summary.is_contiguous is True
    assert summary.row_count == 3

    # Gap in monthly sequence must fail
    df_gap = df_valid.iloc[[0, 2]].reset_index(drop=True)
    is_contig, missing = check_monthly_continuity(df_gap["month"].tolist())
    assert is_contig is False
    assert missing == ["2026-08-01"]
    with pytest.raises(SnapshotValidationError, match="gap"):
        validate_monthly_series_df(df_gap)

    # Duplicate month must fail
    df_dup = pd.concat([df_valid, df_valid.iloc[[1]]], ignore_index=True)
    with pytest.raises(SnapshotValidationError, match="Duplicate"):
        validate_monthly_series_df(df_dup)

    # Non-positive value must fail
    df_neg = df_valid.copy()
    df_neg.loc[1, "value"] = 0.0
    with pytest.raises(SnapshotValidationError, match="Non-positive"):
        validate_monthly_series_df(df_neg)


def test_bad_fixture_rejected_and_no_snapshot_written(tmp_path: Path) -> None:
    bad_ppi_csv = b"series,date,section,index\nabs,2026-07-01,4,-12.5\n"

    with pytest.raises(SnapshotValidationError):
        write_snapshot(
            tmp_path,
            source="dosm",
            dataset="ppi_sitc",
            payload=bad_ppi_csv,
            filename="ppi_sitc.csv",
            request_url="https://storage.dosm.gov.my/ppi/ppi_sitc.csv",
            retrieved_at_utc="2026-10-11T08:00:00+00:00",
            validator=lambda data: validate_dataset_payload("ppi_sitc", data, "ppi_sitc.csv"),
        )

    assert latest_snapshot(tmp_path, "dosm", "ppi_sitc") is None
    assert not (tmp_path / "dosm").exists()


def test_sync_revisions_between_two_snapshots(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    revs_path = tmp_path / "processed" / "revisions.parquet"

    csv_1 = b"series,date,section,index\nabs,2026-07-01,4,138.0\nabs,2026-08-01,4,139.0\n"
    csv_2 = b"series,date,section,index\nabs,2026-07-01,4,138.0\nabs,2026-08-01,4,139.9\n"

    write_snapshot(
        raw_root,
        source="dosm",
        dataset="ppi_sitc",
        payload=csv_1,
        filename="ppi_sitc.csv",
        request_url="https://storage.dosm.gov.my/ppi/ppi_sitc.csv",
        retrieved_at_utc="2026-09-28T08:00:00+00:00",
        row_count=2,
    )
    write_snapshot(
        raw_root,
        source="dosm",
        dataset="ppi_sitc",
        payload=csv_2,
        filename="ppi_sitc.csv",
        request_url="https://storage.dosm.gov.my/ppi/ppi_sitc.csv",
        retrieved_at_utc="2026-10-28T08:00:00+00:00",
        row_count=2,
    )

    revs = sync_revisions_from_snapshots(raw_root, revs_path)
    assert len(revs) == 1
    assert revs.iloc[0]["series_id"] == "ppi_oilsfats_my"
    assert revs.iloc[0]["period"] == "2026-08-01"
    assert revs.iloc[0]["old_value"] == pytest.approx(139.0)
    assert revs.iloc[0]["new_value"] == pytest.approx(139.9)
    assert revs_path.is_file()


def test_gate_g1_and_o1_on_ingested_snapshots(tmp_path: Path) -> None:
    cfg = load_config(Path("config/project.yaml"))
    # Point reports_dir and processed_dir to tmp_path while reading raw_dir from repo
    custom_cfg = cfg.model_copy(
        update={
            "paths": cfg.paths.model_copy(
                update={
                    "processed_dir": str(tmp_path / "processed"),
                    "reports_dir": str(tmp_path / "reports"),
                }
            )
        }
    )
    audit = run_data_quality_gate(custom_cfg, root=Path("."))
    assert audit.o1_passed is True
    assert audit.gate_g1_passed is True
    assert audit.palm_wb_myr_months >= 180
    assert audit.ppi_oilsfats_my_months >= 200
    assert audit.selected_primary_target == "palm_wb_myr"
    assert (tmp_path / "reports" / "data_quality.md").is_file()
    assert (tmp_path / "reports" / "data_quality_audit.json").is_file()
