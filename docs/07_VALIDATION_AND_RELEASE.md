# 07. Validation and Release Protocol

Status: APPROVED, 2026-10-12.

## 1. Fresh-Clone Reproduction Guide (Gate G7)

To reproduce the entire PalmGuard codebase, validation suite, and pipeline execution from scratch on a clean machine:

### Step 1: Environment Setup
```bash
git clone https://github.com/luqshzeeq3601-art/08_PalmGuard_Malaysian_Commodity_Forecasting.git
cd 08_PalmGuard_Malaysian_Commodity_Forecasting
python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate
```

### Step 2: Install Locked Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.lock.txt
pip install -e ".[dev]"
```

### Step 3: Run Diagnostic Doctor (Gate G0)
```bash
palmguard doctor
```
Expected output:
- Python 3.11 -> PASS
- 17 required packages installed -> PASS
- DuckDB window function execution -> PASS
- Writable directories created -> PASS

### Step 4: Run Automated Test Suite (Gates G0 to G6)
```bash
pytest
```
Expected output: 83 tests passing, 0 errors, offline mock protections enforced.

### Step 5: Execute Sequential Production Pipeline (Gate G5)
```bash
palmguard pipeline run --offline
```
Output:
- Ingest & contract check (Gate G1)
- DuckDB monthly panel and SQL feature build (Gate G2)
- Score historical forecast ledger
- Refit frozen champion models (B1 for palm oil, B3 for PPI)
- Update append-only ledger `data/processed/forecast_ledger.parquet`
- Drift audit with PSI and KS tests
- Published artifacts written to `reports/published/`

### Step 6: Test REST API & Smoke Test (Gate G6)
```bash
uvicorn palmguard.api:app --host 127.0.0.1 --port 8000 &
python scripts/smoke_api.py --base-url http://127.0.0.1:8000
```
Expected output:
- `/health` 200
- `/ready` 200 (artifacts loaded, champions returned)
- `/forecast` 200 (6 forecasts with 80% and 90% bands)
- `/history` 200
- `/monitoring` 200
- All API smoke tests PASSED.

---

## 2. Release Evidence & Gates Status

| Gate | Requirement | Status | Evidence Location |
| :--- | :--- | :--- | :--- |
| **G0** | Package installs, doctor passes | **PASSED** | CLI test, requirements.lock.txt |
| **G1** | Provenance, contracts, target definition | **PASSED** | `reports/data_quality.md`, `09_DECISIONS_LOG.md` |
| **G2** | Leakage test suite green, split manifest frozen | **PASSED** | `data/processed/split_manifest.json`, `tests/test_features.py` |
| **G3** | Validation selection complete, record frozen | **PASSED** | `artifacts/champion/selection_record.json`, `reports/validation_metrics.csv` |
| **G4** | Holdout scored once with single-run guard | **PASSED** | `artifacts/champion/holdout_guard.json`, `reports/holdout_metrics.csv` |
| **G5** | Pipeline idempotent on fixtures; a manual workflow dispatch publishes | **PASSED** | Idempotency: `tests/test_pipeline.py`. Manual dispatch run 38191449036 on 2026-10-12 succeeded and committed `reports/published/` |
| **G6** | CI green including container smoke test; public URLs pass the smoke test | **PARTIAL** | CI run 38191218340 green on 2026-10-12, including Docker build and container smoke test. No public URL yet (T23) |
| **G7** | Fresh-clone reproduction verified | **PASSED** | 2026-10-12: fresh clone, new Python 3.11 virtualenv, install from `requirements.lock.txt`: doctor PASS, 81 tests pass, `palmguard pipeline run --offline` succeeds, `pip freeze` matches the lock file. O5 pending (no scheduled run yet) |
