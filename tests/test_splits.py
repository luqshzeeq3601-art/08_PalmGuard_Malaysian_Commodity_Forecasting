"""Tests for rolling-origin splits and Gate G2 manifest (Task T09)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from palmguard.config import TargetConfig, load_config
from palmguard.splits import (
    build_series_split,
    compute_series_hash,
    load_split_manifest,
    run_split_gate,
)


@pytest.fixture
def sample_synthetic_panel() -> pd.DataFrame:
    """Generate a clean synthetic 200-month panel for two series."""
    # 200 contiguous months from 2010-01-01
    dt_index = pd.date_range("2010-01-01", periods=200, freq="MS")
    rows: list[dict[str, object]] = []
    for dt in dt_index:
        m_str = dt.strftime("%Y-%m-%d")
        rows.append(
            {
                "series_id": "palm_wb_myr",
                "month": m_str,
                "value": 3000.0 + float(len(rows)),
                "available_from": m_str,
                "snapshot_id": "snap_1",
                "is_provisional": False,
            }
        )
        rows.append(
            {
                "series_id": "ppi_oilsfats_my",
                "month": m_str,
                "value": 100.0 + float(len(rows) * 0.1),
                "available_from": m_str,
                "snapshot_id": "snap_1",
                "is_provisional": False,
            }
        )
    return pd.DataFrame(rows)


def test_series_hash_determinism(sample_synthetic_panel: pd.DataFrame) -> None:
    """Verify SHA-256 series hash is stable and changes when values are perturbed."""
    s_df = sample_synthetic_panel[sample_synthetic_panel["series_id"] == "palm_wb_myr"]
    h1 = compute_series_hash(s_df)
    h2 = compute_series_hash(s_df.copy())
    assert h1 == h2
    assert len(h1) == 64

    # Perturb one value
    perturbed = s_df.copy()
    perturbed.loc[perturbed.index[10], "value"] += 1.0
    h3 = compute_series_hash(perturbed)
    assert h1 != h3


def test_no_validation_target_inside_holdout_range(sample_synthetic_panel: pd.DataFrame) -> None:
    """Verify that validation targets strictly precede the holdout target range (no leakage)."""
    target_cfg = TargetConfig(
        series_id="palm_wb_myr",
        display_name="Palm Oil Test",
        short_description="Test",
        unit="RM/mt",
        min_history_months=180,
        min_training_months=100,
        validation_origins=30,
        holdout_origins=20,
    )

    manifest = build_series_split(sample_synthetic_panel, target_cfg, horizons=[1, 2, 3])

    assert manifest.validation_origins_count == 30
    assert manifest.holdout_origins_count == 20
    assert manifest.embargo_months == 3

    val_targets = set()
    for f in manifest.validation_folds:
        for t in f.target_months.values():
            val_targets.add(t)

    hold_targets = set()
    for f in manifest.holdout_folds:
        for t in f.target_months.values():
            hold_targets.add(t)

    # 1. Zero overlap between validation targets and holdout targets
    assert val_targets.isdisjoint(hold_targets)

    # 2. Maximum validation target is strictly less than the minimum holdout target
    assert max(val_targets) < min(hold_targets)

    # 3. Maximum validation target is <= first holdout origin (cannot touch holdout targets)
    first_holdout_origin = manifest.holdout_folds[0].origin_month
    assert max(val_targets) <= first_holdout_origin


def test_minimum_training_months_assertion(sample_synthetic_panel: pd.DataFrame) -> None:
    """Verify build_series_split raises ValueError when initial training months are insufficient."""
    # Sample panel has 200 months. If holdout=24, embargo=3, val=60:
    # First validation origin has index 200 - 24 - 3 - 60 = 113 -> 114 training months.
    # Requesting min_training_months=130 should fail.
    target_cfg = TargetConfig(
        series_id="palm_wb_myr",
        display_name="Palm Oil Test",
        short_description="Test",
        unit="RM/mt",
        min_history_months=180,
        min_training_months=130,  # exceeds available 114
        validation_origins=60,
        holdout_origins=24,
    )

    with pytest.raises(ValueError, match="failing minimum requirement"):
        build_series_split(sample_synthetic_panel, target_cfg, horizons=[1, 2, 3])


def test_expanding_training_window_invariance(sample_synthetic_panel: pd.DataFrame) -> None:
    """Verify that training window monotonically expands across rolling origins."""
    target_cfg = TargetConfig(
        series_id="palm_wb_myr",
        display_name="Palm Oil Test",
        short_description="Test",
        unit="RM/mt",
        min_history_months=180,
        min_training_months=50,
        validation_origins=12,
        holdout_origins=12,
    )

    manifest = build_series_split(sample_synthetic_panel, target_cfg, horizons=[1, 2, 3])

    # Check validation folds expansion
    prev_count = 0
    for fold in manifest.validation_folds:
        assert fold.training_start_month == "2010-01-01"
        assert fold.training_end_month == fold.origin_month
        assert fold.training_months_count > prev_count
        prev_count = fold.training_months_count

    # Check holdout folds expansion
    for fold in manifest.holdout_folds:
        assert fold.training_start_month == "2010-01-01"
        assert fold.training_end_month == fold.origin_month
        assert fold.training_months_count > prev_count
        prev_count = fold.training_months_count


def test_live_data_split_manifest_and_gate_g2(tmp_path: Path) -> None:
    """Verify Gate G2 execution against committed live repository data."""
    raw_root = Path("data/raw")
    if not (raw_root / "worldbank" / "pink_sheet").exists():
        pytest.skip("data/raw not present")

    cfg = load_config("config/project.yaml")
    manifest_out = tmp_path / "split_manifest.json"

    ok, manifest = run_split_gate(cfg, root=Path("."), manifest_path=manifest_out)
    assert ok is True
    assert manifest_out.is_file()

    # Verify primary target: palm_wb_myr
    palm = manifest.series["palm_wb_myr"]
    assert palm.total_months_count == 281
    assert palm.validation_origins_count == 60
    assert palm.holdout_origins_count == 24
    assert palm.min_training_months_required == 120
    assert palm.validation_folds[0].training_months_count >= 120
    assert len(palm.validation_folds) == 60
    assert len(palm.holdout_folds) == 24

    # Verify secondary target: ppi_oilsfats_my
    ppi = manifest.series["ppi_oilsfats_my"]
    assert ppi.total_months_count == 200
    assert ppi.validation_origins_count == 48
    assert ppi.holdout_origins_count == 24
    assert ppi.min_training_months_required == 96
    assert ppi.validation_folds[0].training_months_count >= 96
    assert len(ppi.validation_folds) == 48
    assert len(ppi.holdout_folds) == 24

    # Verify serialization and reloading matches schema
    loaded = load_split_manifest(manifest_out)
    assert loaded.project_name == "PalmGuard"
    assert loaded.frozen_vintage_date == "2026-10-11"
    assert set(loaded.series.keys()) == {"palm_wb_myr", "ppi_oilsfats_my"}
