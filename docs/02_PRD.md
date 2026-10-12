# 02. Product requirements

Status: DRAFT, 2026-10-11.

## 1. Users and their questions

| User | Question | Surface |
| --- | --- | --- |
| Reviewer / hiring manager | Is the evaluation honest and does the system run? | README, model card, dashboard |
| Analyst | What is the forecast and how wide is the uncertainty? | Dashboard, `/forecast` |
| Engineer | Can I reproduce it and see it run on a schedule? | CLI, CI, pipeline workflow |

## 2. Functional requirements

### FR1 Ingestion

1. Pull from the data.gov.my API (exchange rates, PPI, trade) and the World Bank Pink Sheet (sources in 03_DATA_SPEC.md). All are CC BY 4.0.
2. Write each pull as a dated, immutable raw snapshot with a manifest (URL, SHA-256, bytes, retrieval time, schema version).
3. Repeating a pull with unchanged content creates no new snapshot.
4. Validate schema before accepting a snapshot. A failed check stops the run.
5. Respect the data.gov.my limit of 4 requests per minute; back off on HTTP 429 and 5xx.
6. Log value differences between consecutive snapshots (revisions).

### FR2 SQL feature layer

1. All lag, rolling and calendar features are DuckDB SQL window functions stored in `queries/`.
2. Features for an origin use only data published by that origin, at the vintage that existed then.
3. Tests prove no future leakage (03_DATA_SPEC.md section 7, 04_TECHNICAL_DESIGN.md section 4).

### FR3 Forecast models

1. Baselines first: naive, seasonal naive, ETS, ARIMA.
2. LightGBM with lag features; a second variant adds exogenous drivers that are known at forecast time.
3. Model choice follows 05_FORECAST_EXPERIMENT_PLAN.md. A baseline may win.

### FR4 Prediction intervals

1. 80% and 90% intervals per horizon from conformal methods suited to time series.
2. Coverage is reported as measured. The word "guaranteed" is not used.

### FR5 Scheduled pipeline

1. GitHub Actions cron: monthly full run, weekly ingest-only run, manual dispatch.
2. Steps: ingest, validate, build features, score earlier forecasts against new actuals, refit and forecast, monitor, publish.
3. The forecast ledger is append-only. A forecast, once published, is never edited.

### FR6 Monitoring

1. Rolling forecast error (MASE, absolute percentage error) per horizon over time.
2. Rolling empirical interval coverage against nominal.
3. Data drift check on returns and features against the training reference.

### FR7 Interfaces

| Interface | Requirement |
| --- | --- |
| CLI `palmguard` | `doctor`, `ingest`, `features`, `backtest`, `select`, `holdout`, `forecast`, `score`, `monitor`, `pipeline run`, `report` |
| FastAPI | `/health`, `/ready`, `/forecast`, `/history`, `/monitoring`; typed responses; reads published artifacts only |
| Streamlit dashboard | Forecast with interval bands, past forecast versus actual, error by horizon, coverage over time, drift status, attribution and disclaimer |
| Docker | One image for the API; runtime smoke test in CI |
| Public deployment | API on Render free tier, dashboard on Streamlit Community Cloud, both smoke-tested |

### FR8 Documentation

README with measured results, model card, docs 00 to 11, decisions and progress logs.

## 3. Non-functional requirements

- Reproducible: seed 42, locked dependencies, config-driven, artifacts record data vintage and code revision.
- Offline tests: CI never calls a live source.
- Polite to sources: low request volume, identifying User-Agent, no parallel requests.
- Typed functions, explicit schemas, small modules, ruff clean.
- No secrets in the repository. Tokens live in GitHub Actions secrets.

## 4. Exclusions

Daily data, futures, trading logic, Prefect, paid cloud, user accounts, model upload endpoints, hyperparameter search beyond the declared grid.

## 5. Acceptance per deliverable

| Deliverable | Accepted when |
| --- | --- |
| Ingestion | Idempotency, immutability and bad-schema tests pass; one live run writes manifests |
| Feature layer | Leakage test suite passes; hand-computed fixtures reconcile |
| Models and intervals | Validation and holdout reports exist; selection record predates holdout scoring |
| Pipeline | Second run on unchanged data is a no-op; ledger append-only test passes; three scheduled runs succeed |
| API and Docker | CI builds the image and the container smoke test passes |
| Dashboard | Loads from fixture artifacts in a headless test; shows disclaimer and attribution |
| Deployment | Smoke test passes against public URLs; evidence logged with timestamp |
| Docs | Every reported number traces to a file in `reports/` |
