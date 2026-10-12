# 04. Technical design

Status: DRAFT, 2026-10-11. Structure follows `03_DemandGuard_Demand_Forecasting_Inventory_Optimisation`.

## 1. Layout

```
08_PalmGuard_Malaysian_Commodity_Forecasting/
  AGENTS.md  README.md  LICENSE  pyproject.toml  requirements.lock.txt
  Dockerfile  .dockerignore  .gitignore  render.yaml
  .github/workflows/  ci.yml  pipeline.yml  live-contract.yml
  config/project.yaml
  queries/  monthly_panel.sql  features.sql  calendar.sql  scoring.sql
  src/palmguard/
    cli.py  config.py  contracts.py  http.py
    ingest/  datagovmy.py  worldbank.py  snapshots.py
    features.py  splits.py  baselines.py  model.py  conformal.py
    evaluation.py  pipeline.py  monitoring.py  reporting.py  api.py
  dashboard/app.py
  scripts/  smoke_api.py  deploy_cloud_run.ps1
  tests/  fixtures/  conftest.py  test_*.py
  docs/  tasks/  data/  artifacts/  reports/
```

## 2. Conventions carried over from DemandGuard

- `pyproject.toml`: setuptools, `src/` layout, Python `>=3.10,<3.13` (3.11 in CI and Docker), ruff rules `E,F,I,W`, line length 100, pytest `-q -p no:cacheprovider`, console script `palmguard`.
- Lock file: `requirements.lock.txt`.
- Config in `config/project.yaml`; MLflow at `sqlite:///mlflow.db` for backtests only.
- Docker: `python:3.11-slim`, `libgomp1`, healthcheck on `/health`, uvicorn on port 8000.
- CI: ruff check, ruff format check, pytest with coverage, Docker build, container start, poll `/ready`, `scripts/smoke_api.py`.
- Docs 00 to 11, MODEL_CARD.md, `tasks/todo.md` as the only status tracker, gates G0 to G7.

Dependencies: duckdb, fastapi, httpx, lightgbm, matplotlib, mlflow, numpy, openpyxl, pandas, pyarrow, pydantic, pyyaml, scikit-learn, scipy, statsmodels, streamlit, uvicorn. Dev: pytest, pytest-cov, ruff. MAPIE only if T13 keeps it.

## 3. Ingestion

`http.py`: one httpx client factory with timeout, identifying User-Agent, retry with exponential backoff on 429 and 5xx, and a per-host minimum interval (16 s for `api.data.gov.my`). The client is passed in, so tests substitute `httpx.MockTransport`.

| Module | Behaviour |
| --- | --- |
| `ingest/snapshots.py` | Hashing, snapshot paths, manifest writing, idempotency, immutability, revision diff |
| `ingest/datagovmy.py` | Datasets `exchangerates_daily_1700`, `ppi_sitc`, `trade_sitc_1d`, `sitc`. Backfill from the storage parquet/CSV once; incremental pulls through the API with a date filter and `limit` |
| `ingest/worldbank.py` | Resolve the current xlsx link from the landing page, download, read the monthly sheet and notes with openpyxl |
| `contracts.py` | Pydantic models and explicit checks per source and per processed table |

Storage: every source is CC BY 4.0, so snapshots are committed to the public repository by the pipeline. No private repository or access token is needed.

## 4. SQL feature layer

DuckDB runs SQL files from `queries/`; `features.py` only loads parameters, executes and validates output.

- `monthly_panel.sql`: series by month as of a vintage date (`available_from <= :as_of`), latest snapshot per month within that limit.
- `calendar.sql`: month of year, quarter, target month for each horizon.
- `features.sql`: one row per (origin month, horizon).
  - `r1 = ln(y[t] / y[t-1])` and lags of it at 1, 2, 3, 6, 12 via `LAG`.
  - Rolling mean and standard deviation of `r1` over 3, 6, 12 months: `ROWS BETWEEN n-1 PRECEDING AND CURRENT ROW`.
  - Distance from 12-month high and low.
  - Exogenous returns and levels shifted by declared lag minus one relative to the origin row.
  - Target `ln(y[t+h] / y[t])` via `LEAD`, kept in a separate label column.
- `scoring.sql`: joins the forecast ledger to actuals for error and coverage.

Leakage tests:

1. Future mutation: change every value after origin `t`; all feature rows with origin ≤ `t` are unchanged.
2. Hand-computed fixture for each lag and window.
3. Static check on SQL text: no `FOLLOWING` outside the label column; no exogenous lag below its declared publication lag.
4. Vintage: features at origin `t` built with `as_of = t` ignore snapshots retrieved later.
5. Label cutoff: a training row is excluded when its target month is after the fold cutoff.

## 5. Models and intervals

`baselines.py`: B1 naive, B2 seasonal naive, B3 ETS, B4 ARIMA (statsmodels). `model.py`: LightGBM M1 and M2, one model per horizon. `conformal.py`: rolling split-conformal residual quantiles and adaptive conformal inference, both per horizon and independent of the point forecaster. Details in 05_FORECAST_EXPERIMENT_PLAN.md.

Champion bundle `artifacts/champion/`: `metadata.json` (model id, parameters, feature list, vintage, code revision, package versions), model file where applicable, `conformal_state.json`, `selection_record.json`. Only local trusted artifacts are loaded.

## 6. Pipeline

`pipeline.py` runs these steps in order; each is also a CLI command.

1. `ingest`: pull, validate, snapshot.
2. `features`: build panel and features for the new vintage.
3. `score`: for ledger rows whose target month now has an actual, append error and interval hit to `scores.parquet`.
4. `forecast`: refit the frozen champion configuration on the expanded window; forecast h = 1..3 with intervals; append to the ledger; update conformal state.
5. `monitor`: rolling MASE, rolling coverage, drift flags to `reports/published/monitoring.json`.
6. `publish`: write `reports/published/` and commit.

`forecast_ledger.parquet` key: origin month, target month, horizon, model version, vintage. Append-only; a test rejects any change to an existing row.

Refit policy: the champion's type, features and hyperparameters are frozen at selection. Coefficients are refitted each month on the expanding window. This is stated in the model card.

`.github/workflows/pipeline.yml`: cron monthly on the 8th (full run) and weekly (ingest only), plus `workflow_dispatch`. Concurrency group prevents overlapping runs. The job commits new snapshots and `reports/published/` with the Actions bot identity, using the default `GITHUB_TOKEN` with `contents: write`.

The pipeline runs once per series in `config/project.yaml` (`palm_wb_myr`, `ppi_oilsfats_my`); ledger, scores and monitoring rows carry `series_id`.

## 7. Serving

| Endpoint | Response |
| --- | --- |
| `GET /health` | Process alive |
| `GET /ready` | Published artifacts loaded; returns model version and vintage |
| `GET /forecast?series=&horizon=` | Series definition, origin, target months, point forecast, 80% and 90% bounds, units, vintage, disclaimer |
| `GET /history?limit=` | Past forecasts with actuals, errors and interval hits |
| `GET /monitoring` | Rolling error, rolling coverage, drift status |

The API and dashboard read `reports/published/` only. Neither calls a live source or accepts a model path.

`dashboard/app.py` (Streamlit): forecast chart with bands; forecast versus actual history; error by horizon; coverage over time against nominal; drift panel; sources, licences and disclaimer. Backtest and live scores are labelled separately.

## 8. Deployment

- API: Docker web service on Render free tier via `render.yaml`, auto-deploy on push to main. Cold starts are expected.
- Dashboard: Streamlit Community Cloud from the public repository.
- Verification: `python scripts/smoke_api.py --base-url <url>` checks `/ready`, `/forecast` and `/history`; result and timestamp go to the progress log.
- `scripts/deploy_cloud_run.ps1` follows the DemandGuard script and is marked unverified until a billing-enabled project exists.

## 9. Tests and CI without the live API

- `tests/fixtures/`: recorded data.gov.my JSON responses (small), a small xlsx in the Pink Sheet layout, and a small synthetic monthly panel.
- An autouse fixture fails any test that constructs a real HTTP client.
- `pytest -m live` runs contract checks against real sources; excluded from `ci.yml`, run by `live-contract.yml` weekly and on demand.
- The Docker image used in CI serves demo artifacts built from fixtures.

## 10. Monitoring and drift

- Rolling 12-month MASE and absolute percentage error per horizon.
- Rolling 12 and 24-month empirical coverage at 80% and 90%.
- Drift: PSI and two-sample KS on monthly returns and each feature, recent 24 months against the training reference. Thresholds are set in config before the first live run.
- A drift flag is informational; it does not trigger automatic retuning.
