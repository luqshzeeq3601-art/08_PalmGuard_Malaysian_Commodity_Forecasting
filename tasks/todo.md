# PalmGuard implementation checklist

## 1. Status and rules

- Current status: 24/25 complete, Gates G0 to G5 and G7 passed, 2026-10-12. Only T23 (public deployment, G6) remains; it needs Render and Streamlit Community Cloud accounts.
- Next task: T23.
- Tick a task only after its acceptance and verification pass; record evidence in ../docs/10_PROGRESS_LOG.md.
- Size: S = 1-2 implementation files; M = 3-5.
- Commands are planned interfaces until the owning task implements them.

## 2. Foundation

- [x] **T01 — Package, lock file and tooling**
  - Acceptance: editable install works on Python 3.11; `palmguard doctor` reports versions; lock file has no local editable paths.
  - Verify: `pip install -e ".[dev]"`, `palmguard doctor`, `ruff check src tests`, `pytest`; G0.
  - Dependencies: none. Size: M.
  - Files: pyproject.toml, requirements.lock.txt, .gitignore, src/palmguard/__init__.py, src/palmguard/cli.py.

- [x] **T02 — HTTP client and immutable snapshot store**
  - Acceptance: identical payload twice gives one snapshot; an existing snapshot is never rewritten; 429 and 5xx trigger backoff; per-host throttle applied.
  - Verify: tests with `httpx.MockTransport`; a test that a real client in tests raises.
  - Dependencies: T01. Size: M.
  - Files: src/palmguard/http.py, src/palmguard/ingest/snapshots.py, tests/conftest.py, tests/test_snapshots.py, tests/test_http.py.

## 3. Data

- [x] **T03 — World Bank Pink Sheet ingestor**
  - Acceptance: xlsx link resolved from the landing page; palm oil, Brent and soybean oil columns, start dates and the palm oil definition by period (crude or refined, delivery basis) read from the file and recorded in 03_DATA_SPEC.md.
  - Verify: fixture xlsx test; one live run writes a manifest. If no usable palm oil column exists, stop and record the PPI fallback.
  - Dependencies: T02. Size: S.
  - Files: src/palmguard/ingest/worldbank.py, tests/test_worldbank.py.

- [x] **T04 — data.gov.my API ingestor**
  - Acceptance: date filter syntax confirmed from the official docs; datasets `exchangerates_daily_1700`, `ppi_sitc`, `trade_sitc_1d`, `sitc`; backfill from bulk files, incremental through the API.
  - Verify: mocked tests for paging, filter and 429; one live run writes a manifest per dataset; PPI section 4 has at least 200 monthly rows.
  - Dependencies: T02. Size: S.
  - Files: src/palmguard/ingest/datagovmy.py, tests/test_datagovmy.py.

- [x] **T05 — Publication timing and target freeze**
  - Acceptance: publication days of the Pink Sheet, PPI and trade releases recorded; lag table in config confirmed or corrected; target definition and wording frozen in 09_DECISIONS_LOG.md; Q3 answered.
  - Verify: lag values in `config/project.yaml` match 03_DATA_SPEC.md section 5; decision entry dated before any model code.
  - Dependencies: T03, T04. Size: S.
  - Files: config/project.yaml, docs/09_DECISIONS_LOG.md.

- [x] **T06 — Contracts, revisions log and data quality gate**
  - Acceptance: a bad fixture is rejected and no snapshot written; revisions between two snapshots logged; `reports/data_quality.md` written; G1 decision (palm oil target or PPI fallback) recorded.
  - Verify: `palmguard ingest` then contract tests; O1 checked.
  - Dependencies: T05. Size: M.
  - Files: src/palmguard/contracts.py, src/palmguard/config.py, config/project.yaml, tests/test_contracts.py.

**Checkpoint G1:** PASSED (2026-10-12) — provenance, continuity, attribution and target definition settled.

## 4. Features and splits

- [x] **T07 — Monthly panel in SQL**
  - Acceptance: one row per series and month as of a vintage; monthly FX mean and MYR conversion computed in SQL.
  - Verify: hand-computed fixture reconciles; vintage test (later snapshots ignored) passes.
  - Dependencies: T06. Size: S.
  - Files: queries/monthly_panel.sql, src/palmguard/features.py, tests/test_panel.py.

- [x] **T08 — Feature SQL with leakage tests**
  - Acceptance: lags, rolling statistics and calendar features are window functions; publication lags enforced.
  - Verify: future-mutation, hand-computed, static no-`FOLLOWING`, publication-lag and label-cutoff tests pass (O4).
  - Dependencies: T07. Size: M.
  - Files: queries/features.sql, queries/calendar.sql, src/palmguard/features.py, tests/test_features.py.

- [x] **T09 — Frozen split manifest**
  - Acceptance: per series, validation and holdout origins (palm oil 60/24, PPI 48/24) with target months, vintage and hashes written before any fit.
  - Verify: no validation target inside the holdout range; minimum training months (120 and 96) asserted.
  - Dependencies: T07. Size: S.
  - Files: src/palmguard/splits.py, tests/test_splits.py.

**Checkpoint G2:** PASSED (2026-10-12) — leakage suite green and manifest frozen.

## 5. Models and evaluation

- [x] **T10 — Metrics**
  - Acceptance: MASE, WAPE, pinball loss, coverage with binomial interval, width, bias; zero-denominator rules defined.
  - Verify: hand-calculated fixtures.
  - Dependencies: T09. Size: S.
  - Files: src/palmguard/evaluation.py, tests/test_metrics.py.

- [x] **T11 — Baselines B1-B4**
  - Acceptance: every validation origin and horizon has a row per baseline; fit failures logged with B1 fallback.
  - Verify: `palmguard backtest --models baselines`; alignment tests.
  - Dependencies: T10. Size: S.
  - Files: src/palmguard/baselines.py, tests/test_baselines.py.

- [x] **T12 — LightGBM M1 and M2**
  - Acceptance: grid written to config before running; one model per horizon; MLflow runs logged; training labels respect fold cutoffs.
  - Verify: `palmguard backtest --models lgbm`; cutoff test; deterministic output with seed 42.
  - Dependencies: T08, T10. Size: S.
  - Files: src/palmguard/model.py, tests/test_model.py.

- [x] **T13 — Conformal intervals and MAPIE spike**
  - Acceptance: C1 and C2 per horizon using only residuals observed by each origin; MAPIE keep-or-drop decision logged.
  - Verify: on synthetic exchangeable noise coverage is close to nominal; after a variance shift C2 recovers faster than C1; residual-availability test.
  - Dependencies: T11. Size: S.
  - Files: src/palmguard/conformal.py, tests/test_conformal.py.

- [x] **T14 — Validation selection**
  - Acceptance: champion and interval method chosen by the rules in 05 section 8; `selection_record.json` written with timestamp.
  - Verify: `palmguard select`; `reports/validation_metrics.csv` complete; G3.
  - Dependencies: T12, T13. Size: S.
  - Files: src/palmguard/evaluation.py, src/palmguard/reporting.py.

- [x] **T15 — Frozen holdout, scored once**
  - Acceptance: 24 origins scored for all candidates; a guard refuses a second run; results stated against O2 and O3.
  - Verify: `palmguard holdout`; guard test; `reports/forecast_comparison.md`; G4.
  - Dependencies: T14. Size: S.
  - Files: src/palmguard/evaluation.py, tests/test_holdout.py.

## 6. Pipeline and monitoring

- [x] **T16 — End-to-end pipeline**
  - Acceptance: ingest, features, score, forecast, monitor, publish in order; append-only ledger.
  - Verify: two runs on fixtures, second reports no change; ledger immutability test.
  - Dependencies: T15. Size: M.
  - Files: src/palmguard/pipeline.py, queries/scoring.sql, tests/test_pipeline.py.

- [x] **T17 — Monitoring and drift**
  - Acceptance: rolling MASE and coverage; PSI and KS drift with thresholds from config.
  - Verify: a shifted fixture raises the drift flag; rolling values match hand calculation.
  - Dependencies: T16. Size: S.
  - Files: src/palmguard/monitoring.py, tests/test_monitoring.py.

- [x] **T18 — Scheduled workflow and publish**
  - Acceptance: monthly and weekly cron, manual dispatch, concurrency guard; new snapshots and published artifacts committed with the default token.
  - Verify: manual dispatch succeeds and a commit to `data/raw/` and `reports/published/` appears; workflow permissions documented in 08_OPERATIONS_AND_COMMANDS.md; G5.
  - Dependencies: T17. Size: S.
  - Files: .github/workflows/pipeline.yml, .github/workflows/live-contract.yml.

## 7. Delivery

- [x] **T19 — CLI**
  - Acceptance: all commands in 02_PRD.md FR7 exist with help text.
  - Verify: CLI tests; commands listed in 08_OPERATIONS_AND_COMMANDS.md.
  - Dependencies: T16. Size: S.
  - Files: src/palmguard/cli.py, tests/test_cli.py.

- [x] **T20 — FastAPI service**
  - Acceptance: five endpoints with typed responses, reading published artifacts only; invalid horizon rejected.
  - Verify: `tests/test_api.py` with the test client.
  - Dependencies: T19. Size: S.
  - Files: src/palmguard/api.py, tests/test_api.py.

- [x] **T21 — Docker and CI**
  - Acceptance: image builds; container passes the smoke test in CI; no test uses the network.
  - Verify: CI run green on GitHub.
  - Dependencies: T20. Size: M.
  - Files: Dockerfile, .dockerignore, .github/workflows/ci.yml, scripts/smoke_api.py, tests/test_container_contract.py.

- [x] **T22 — Streamlit dashboard**
  - Acceptance: forecast with bands, forecast versus actual, error by horizon, coverage over time, drift, attribution and disclaimer; backtest and live labelled.
  - Verify: headless Streamlit app test on fixture artifacts.
  - Dependencies: T17. Size: S.
  - Files: dashboard/app.py, tests/test_dashboard.py.

- [ ] **T23 — Public deployment** (`render.yaml` written; nothing deployed, smoke test passed on localhost only)
  - Acceptance: API on Render and dashboard on Streamlit Community Cloud serve the published forecast; free-tier terms rechecked.
  - Verify: `python scripts/smoke_api.py --base-url <url>` passes; dashboard URL checked by hand; evidence logged; G6 and O6.
  - Dependencies: T18, T21, T22. Needs Q1. Size: S.
  - Files: render.yaml, scripts/deploy_cloud_run.ps1 (unverified).

## 8. Release

- [x] **T24 — Model card and README with measured results**
  - Acceptance: every number traces to a file in `reports/`; missed targets stated; disclaimer present.
  - Verify: manual trace of each figure; links resolve.
  - Dependencies: T23. Size: S.
  - Files: README.md, docs/MODEL_CARD.md.

- [x] **T25 — Fresh-clone reproduction** (clean lock-file install verified 2026-10-12; O5 recorded as pending)
  - Acceptance: a clean clone installs from the lock file, passes tests and runs the fixture pipeline; O5 status recorded.
  - Verify: commands and output in 10_PROGRESS_LOG.md; G7.
  - Dependencies: T24. Size: S.
  - Files: docs/07_VALIDATION_AND_RELEASE.md, docs/10_PROGRESS_LOG.md.
