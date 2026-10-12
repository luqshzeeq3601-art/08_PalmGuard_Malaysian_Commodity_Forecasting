# 08. Operations and commands

Status: APPROVED, 2026-10-12.

## 1. CLI commands reference

PalmGuard exposes a unified CLI executable via `palmguard`:

| Command | Purpose | Typical invocation |
| --- | --- | --- |
| `palmguard doctor` | Check runtime environment, package versions, and DuckDB window capability (Gate G0) | `palmguard doctor` |
| `palmguard ingest` | Ingest external sources into dated raw snapshots with manifests (Gate G1) | `palmguard ingest --mode incremental` |
| `palmguard features` | Build monthly panel and extract SQL lag and driver features | `palmguard features` |
| `palmguard splits` | Verify leakage constraints and freeze split manifest (Gate G2) | `palmguard splits` |
| `palmguard backtest` | Run rolling-origin backtests for baselines and LightGBM models | `palmguard backtest --models all --split validation` |
| `palmguard select` | Execute Gate G3 validation selection protocol and freeze champion bundle | `palmguard select` |
| `palmguard holdout` | Score frozen champion and all candidates on holdout split once (Gate G4); `--intervals-only` reports interval coverage without rescoring | `palmguard holdout` |
| `palmguard pipeline run` | Execute full sequential pipeline: ingest, panel, score, forecast, monitor, publish (Gate G5). `--offline` skips ingestion and reproduces the frozen vintage | `palmguard pipeline run` |
| `palmguard score` | Score forecast ledger against observed actuals | `palmguard score` |
| `palmguard monitor` | Run PSI and KS drift checks and update monitoring report | `palmguard monitor` |
| `palmguard report` | Compile markdown reports comparing forecasts and errors | `palmguard report` |

---

## 2. GitHub Actions scheduled workflows

The project operates two automated GitHub Actions workflows:

1. **`.github/workflows/pipeline.yml`**:
   - **Monthly schedule (`0 3 8 * *`)**: Runs on the 8th of each month at 03:00 UTC (11:00 MYT). Pulls latest Pink Sheet and BNM FX actuals, scores earlier forecasts, refits champions on the expanded sample, produces $h=1..3$ forecasts, executes monitoring, and commits new snapshots, the forecast ledger and published artifacts back to the branch.
   - **Weekly schedule (`0 3 * * 1`)**: Checks for incoming updates in ingest-only mode.
   - **Manual dispatch (`workflow_dispatch`)**: Allows trigger with choices `full` or `ingest-only`.
   - **Permissions**: `contents: write` with the default GitHub Actions token.
   - **Concurrency**: Group `palmguard-pipeline` with `cancel-in-progress: false` to prevent race conditions.

2. **`.github/workflows/live-contract.yml`**:
   - **Weekly schedule (`0 3 * * 3`)**: Runs `palmguard ingest --mode incremental` against the live endpoints and fails on a contract or layout change. Nothing is committed.

---

## 3. Production serving and deployment

- **FastAPI service**:
  - Start local service: `uvicorn palmguard.api:app --host 0.0.0.0 --port 8000`
  - Health checks: `GET /health`, `GET /ready`
  - Endpoints: `GET /forecast`, `GET /history`, `GET /monitoring`
- **Streamlit dashboard**:
  - Start local UI: `streamlit run dashboard/app.py`
  - Sections: Interactive forecast bands, actual vs predicted, error curves by horizon, drift status, data licensing and disclaimer.
