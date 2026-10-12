"""Tests for PalmGuard end-to-end pipeline and monitoring (Tasks T16 & T17)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from palmguard.monitoring import calculate_psi, check_ks_drift
from palmguard.pipeline import execute_pipeline, validate_ledger_immutability


def test_psi_and_ks_drift_calculation():
    """Verify PSI and KS drift flags correctly detect distribution shift."""
    np.random.seed(42)
    # Reference sample ~ N(0, 1)
    ref = np.random.normal(0, 1, 500)
    # Same distribution sample ~ N(0, 1)
    rec_same = np.random.normal(0, 1, 100)

    psi_same = calculate_psi(ref, rec_same)
    _, pval_same, ks_flag_same = check_ks_drift(ref, rec_same, alpha=0.05)
    assert psi_same < 0.25, f"Expected no drift, got PSI={psi_same}"
    assert not ks_flag_same, f"Expected KS p-value > 0.05, got {pval_same}"

    # Shifted sample ~ N(2, 2)
    rec_shift = np.random.normal(2, 2, 100)
    psi_shift = calculate_psi(ref, rec_shift)
    _, _, ks_flag_shift = check_ks_drift(ref, rec_shift, alpha=0.05)
    assert psi_shift >= 0.25, f"Expected PSI >= 0.25 on shifted data, got {psi_shift}"
    assert ks_flag_shift, "Expected KS drift flag to trigger on shifted data"


def test_ledger_immutability_enforcement():
    """Verify that any modification to an existing forecast row raises ValueError."""
    existing = pd.DataFrame(
        [
            {
                "series_id": "palm_wb_myr",
                "origin_month": "2026-08-01",
                "target_month": "2026-09-01",
                "horizon": 1,
                "model_id": "B1",
                "y_pred": 3950.0,
                "q80_lower": 3700.0,
                "q80_upper": 4200.0,
                "q90_lower": 3600.0,
                "q90_upper": 4300.0,
            }
        ]
    )

    # Identical or extended dataframe should pass
    validate_ledger_immutability(existing, existing)

    # Mutated prediction must raise
    mutated = existing.copy()
    mutated.loc[0, "y_pred"] = 4100.0
    with pytest.raises(ValueError, match="Ledger immutability violated"):
        validate_ledger_immutability(existing, mutated)


def test_pipeline_execution_and_idempotency(repo_copy: Path):
    """Verify pipeline runs end-to-end and produces published artifacts idempotently."""
    # Execute pipeline
    result1 = execute_pipeline(root=Path("."), mode="incremental", offline=True)
    assert result1["status"] == "success"
    assert result1["forecast_count"] == 6  # 2 series * 3 horizons

    pub_dir = Path("reports/published")
    assert (pub_dir / "forecast.json").exists()
    assert (pub_dir / "monitoring.json").exists()

    with open(pub_dir / "forecast.json", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["forecasts"]) == 6
    assert "disclaimer" in data

    # Re-run pipeline to verify idempotency (ledger stays intact)
    result2 = execute_pipeline(root=Path("."), mode="incremental", offline=True)
    assert result2["status"] == "success"
