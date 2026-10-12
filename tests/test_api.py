"""Tests for PalmGuard FastAPI service (Task T20)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from palmguard.api import app

client = TestClient(app)


def test_api_health():
    """Verify /health returns 200 alive."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


def test_api_ready():
    """Verify /ready returns 200 with loaded champion metadata."""
    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["artifacts_loaded"] is True
    assert "palm_wb_myr" in data["champions"]


def test_api_forecast_endpoints():
    """Verify /forecast returns typed forecasts, supports filtering and disclaimers."""
    # All forecasts
    resp = client.get("/forecast")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["forecasts"]) >= 6
    assert "disclaimer" in data

    # Filter by series and horizon
    resp_filtered = client.get("/forecast?series=palm_wb_myr&horizon=1")
    assert resp_filtered.status_code == 200
    filtered_data = resp_filtered.json()
    assert len(filtered_data["forecasts"]) == 1
    fc = filtered_data["forecasts"][0]
    assert fc["series_id"] == "palm_wb_myr"
    assert fc["horizon"] == 1
    assert fc["y_pred"] > 0
    assert fc["q80_lower"] < fc["y_pred"] < fc["q80_upper"]

    # Invalid horizon validation
    resp_invalid = client.get("/forecast?horizon=5")
    assert resp_invalid.status_code == 422  # validation error


def test_api_history_and_monitoring():
    """Verify /history and /monitoring endpoints."""
    # History
    resp_hist = client.get("/history?limit=10")
    assert resp_hist.status_code == 200
    data_hist = resp_hist.json()
    assert "count" in data_hist
    assert "history" in data_hist

    # Monitoring
    resp_mon = client.get("/monitoring")
    assert resp_mon.status_code == 200
    mon_data = resp_mon.json()
    assert "palm_wb_myr" in mon_data
    assert "ppi_oilsfats_my" in mon_data
    assert "horizons" in mon_data["palm_wb_myr"]
