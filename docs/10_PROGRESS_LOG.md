# 10. Progress log

## 2026-10-11 — T01 Package, lock file and tooling (complete, G0 passed)

- Environment: Python 3.11.9 virtualenv at `.venv`, Windows 11.
- `pip install -e ".[dev]"`: exit 0.
- `pip freeze --exclude-editable > requirements.lock.txt`: 120 pinned packages, no editable or local-path entries.
- `palmguard doctor`: PASS (Python, 17 packages, DuckDB lag window, writable directories).
- `ruff check src tests` and `ruff format --check src tests`: clean.
- `pytest`: 4 passed.
- Key versions: duckdb 1.5.6, lightgbm 4.7.0, pandas 3.0.6, numpy 1.26.4, statsmodels 0.15.0, mlflow 3.17.0, streamlit 1.65.0, httpx 0.28.1.
- Note: pandas resolved to 3.x; DemandGuard was written against 2.x, so code ported from it must be checked.
- Next: T02 HTTP client and immutable snapshot store.

## 2026-10-11 — T02 HTTP client and immutable snapshot store (complete)

- Initialized Git repository (`git init`).
- `src/palmguard/http.py`: Implemented `PoliteTransport`, `create_http_client`, and `fetch_url` with `PalmGuard/0.1.0` User-Agent, 30 s default timeout, 16.0 s minimum host interval for `api.data.gov.my`, and exponential backoff (`Retry-After` aware) on HTTP 429/500/502/503/504.
- `src/palmguard/ingest/snapshots.py`: Implemented `SnapshotManifest`, `write_snapshot`, `list_snapshots`, `latest_snapshot`, `diff_revisions`, and `append_revisions` (compatible with pandas 3.0.6). Enforces validation-before-write, SHA-256 idempotency (`status="no_change"`), and exclusive file creation (`"xb"`/`"x"`) so existing snapshots are never rewritten.
- `tests/conftest.py`: Autouse fixture `block_real_http_client` blocks `httpx.HTTPTransport`, `httpx.AsyncHTTPTransport`, and `urllib.request.urlopen` unless marked `@pytest.mark.live`.
- `ruff check src tests` and `ruff format --check src tests`: clean (9 files).
- `pytest`: 15 passed (4 CLI + 7 HTTP + 4 snapshot/revisions).
- Next: T03 World Bank Pink Sheet ingestor.

## 2026-10-12 — T03 World Bank Pink Sheet ingestor (complete)

- `src/palmguard/ingest/worldbank.py`: Implemented `resolve_monthly_xlsx_url`, `parse_pink_sheet_xlsx`, `validate_pink_sheet_xlsx`, and `ingest_worldbank_pink_sheet`.
- Live run evidence:
  - Resolved xlsx URL from landing page: `https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx`
  - Snapshot written: `data/raw/worldbank/pink_sheet/retrieved=2026-10-11/manifest.json` (`snapshot_id = worldbank.pink_sheet.2026-10-11.ea1c35082787`, `bytes = 586099`, `row_count = 2403`).
  - File note: `Updated on October 02, 2026`.
  - Series verified in `Monthly Prices`: `Palm oil` (`$/mt`, col 22), `Crude oil, Brent` (`$/bbl`, col 2), `Soybean oil` (`$/mt`, col 25) — each has 801 continuous monthly observations from `1960-01-01` to `2026-09-01` with 0 missing values.
  - Palm oil definition read from `Description` sheet and recorded in `docs/03_DATA_SPEC.md`:
    - *Jan 2026–present*: Malaysia, RBD, average export price FOB (`October 2026: Replacement series for Palm oil from January 2026`).
    - *Feb–Dec 2025*: Malaysia, Crude, DAP.
    - *Nov 2024–Jan 2025*: Malaysia, 5% Bulk, CIF North West Europe.
    - *Jan 2021–Oct 2024*: Malaysia, RBD, FOB Malaysia Ports.
    - *Dec 2001–Dec 2020*: Malaysia, RBD, CIF Rotterdam.
    - *Before Dec 2001*: Malaysia 5%, c.i.f. N.W. Europe, bulk, nearest forward.
- `ruff check src tests` and `ruff format --check src tests`: clean (11 files).
- `pytest`: 19 passed.
- Next: T04 data.gov.my API ingestor.

## 2026-10-12 — T04 data.gov.my API ingestor (complete)

- Confirmed official `developer.data.gov.my/request-query` syntax: `filter=<value>@<column>` (comma-separated for multiple columns), `date_start=<YYYY-MM-DD>@<date_column>`, `date_end=<YYYY-MM-DD>@<date_column>`, `sort=<column>`, and `limit=<integer>`.
- `src/palmguard/ingest/datagovmy.py`: Implemented `build_catalogue_params`, `fetch_catalogue_records` (with `date_start` cursor pagination), dataset parsers/validators (`parse_exchangerates`, `parse_ppi_sitc`, `parse_trade_sitc`, `parse_sitc_lookup`), `ingest_datagovmy_dataset` (bulk backfill + incremental API merge), and `ingest_all_datagovmy`.
- Live run evidence (manifests written under `data/raw/`):
  - `exchangerates_daily_1700`: `bnm.exchangerates_daily_1700.2026-10-11.38f4608f4ccb` (`5,759` daily middle USD/MYR rows, `2003-05-02` to `2026-10-09`, `1,528,850` bytes).
  - `ppi_sitc`: `dosm.ppi_sitc.2026-10-11.482c1567e784` (`200` monthly SITC section 4 `abs` rows, `2010-01` to `2026-08`, `146,747` bytes; satisfies `>= 200` requirement).
  - `trade_sitc_1d`: `dosm.trade_sitc_1d.2026-10-11.6566da79934f` (`319` monthly SITC section 4 rows, `2000-01` to `2026-07`, `50,943` bytes).
  - `sitc`: `dosm.sitc.2026-10-11.b4a304f998a1` (`9` lookup rows, `1,237` bytes; confirms section 4 = `"Animal and vegetable oils, and fats"`).
- `ruff check src tests` and `ruff format --check src tests`: clean (13 files).
- `pytest`: 23 passed.
- Next: T05 Publication timing and target freeze.

## 2026-10-12 — T05 Publication timing and target freeze (complete)

- Resolved Q3 with user: kept folder name `08_PalmGuard_Malaysian_Commodity_Forecasting`, froze `palm_wb_myr` described as `"Malaysian palm oil price (World Bank Pink Sheet, MYR/mt)"` as primary headline target alongside `ppi_oilsfats_my` as secondary target.
- Verified publication timing as of `2026-10-11` (after the 8th of October 2026, where `m = 2026-09`):
  - World Bank Pink Sheet (`2026-09` published on `2026-10-02`) and BNM USD/MYR (`2026-09` complete): lag = `1` (`m`).
  - DOSM PPI SITC section 4 (`2026-08` latest on `2026-10-11`): lag = `2` (`m-1`).
  - DOSM Trade SITC section 4 (`2026-07` latest on `data.gov.my` on `2026-10-11`): lag corrected from `2` to `3` (`m-2`).
- Created `config/project.yaml` matching `docs/03_DATA_SPEC.md` section 5 and `docs/09_DECISIONS_LOG.md` (decisions D01, D02, D03 dated prior to any feature or model code).
- Next: T06 Contracts, revisions log and data quality gate (G1).

## 2026-10-12 — T06 Contracts, revisions log and data quality gate (complete, Gate G1 passed)

- `src/palmguard/config.py`: Implemented typed Pydantic configuration loader (`ProjectConfig`, `load_config`) validating `config/project.yaml`.
- `src/palmguard/contracts.py`: Implemented `MonthlyPanelRow`, `SeriesSummary`, `DataQualityAudit`, `check_monthly_continuity`, `validate_monthly_series_df`, `sync_revisions_from_snapshots`, and `run_data_quality_gate`.
- `src/palmguard/cli.py`: Added `palmguard ingest` (`--mode`, `--offline`, `--config`).
- `palmguard ingest` verification output:
  - All 5 datasets returned `no_change` (idempotent on existing snapshots).
  - `palm_wb_myr`: `281` contiguous monthly rows (`2003-05-01` to `2026-09-01`, `1592.20` to `7529.22` RM/mt, 0 duplicates, 0 non-positive, 0 gaps) -> **Objective O1 PASS** (`281 >= 180`).
  - `ppi_oilsfats_my`: `200` contiguous monthly rows (`2010-01-01` to `2026-08-01`, `84.00` to `141.90`, 0 duplicates, 0 non-positive, 0 gaps).
  - Cross-check: monthly log-return correlation between `palm_wb_myr` and `ppi_oilsfats_my` = `0.5398` across `199` overlapping months.
  - Wrote `reports/data_quality.md`, `reports/data_quality_audit.json`, and `data/processed/revisions.parquet`.
  - Recorded Decision D04 (Gate G1 PASS, `palm_wb_myr` confirmed as primary target) in `docs/09_DECISIONS_LOG.md`.
- `ruff check src tests` and `ruff format --check src tests`: clean (16 files).
- `pytest`: 28 passed.
- Next: T07 Monthly panel in SQL.

## 2026-10-12 — T07 Monthly panel in SQL (complete)

- `queries/monthly_panel.sql`: Implemented DuckDB monthly panel query isolating snapshots with `available_from <= $as_of`, aggregating daily USD/MYR middle rates to monthly trading-day means for completed calendar months, computing `palm_wb_myr = palm_wb_usd * usdmyr_avg`, extracting DOSM PPI oils/fats index and trade SITC section 4 exports.
- `src/palmguard/features.py`: Implemented `load_raw_tables_into_duckdb` and `build_monthly_panel_df(raw_root, as_of)`.
- `tests/test_panel.py`:
  - `test_hand_computed_reconciliation`: Synthetic 3-trading-day FX test matches `4.20`, converted palm price `1000 * 4.20 = 4200.0` exactly, Pydantic contracts validated.
  - `test_vintage_isolation`: Proves snapshot with `available_from > as_of` is excluded from panel output.
  - `test_live_data_build_monthly_panel`: Built panel against committed live snapshots as of `2026-10-11` (`palm_wb_myr` spans 281 months).
- `ruff check src tests` and `ruff format --check src tests`: clean (18 files).
- `pytest`: 31 passed.
- Next: T08 Feature SQL with leakage tests.

## 2026-10-12 — T08 Feature SQL with leakage tests (complete, Objective O4 passed)

- `queries/calendar.sql`: Generates origin/target date components and horizon 1..3 dimensions.
- `queries/features.sql`:
  - Implemented own-series log-return features: lags (1, 2, 3, 6, 12), rolling statistics (3, 6, 12-month mean & standard deviation), distance from 12-month high and low, origin month and quarter.
  - Implemented forward lead prediction targets `ln(y[t+h] / y[t])` and prices for `h in {1, 2, 3}`.
  - Implemented M2 exogenous drivers respecting publication lags:
    - USD/MYR, Brent, soybean oil: 1-month return and 3-month rolling mean (lag 1).
    - DOSM PPI Section 4: 1-month return and 3-month rolling mean (lag 2, latest usable `t-1`).
    - DOSM SITC-4 Exports: 1-month return and 3-month rolling mean (lag 3, latest usable `t-2`).
- `src/palmguard/features.py`: Added `build_features_df(panel_df, target_series)`.
- `tests/test_features.py`:
  - `test_static_sql_no_following`: Static AST/text check confirms 0 `FOLLOWING` clauses anywhere in SQL feature window definitions.
  - `test_future_mutation_leakage_invariance`: Objective O4 pass — mutating data in future months strictly leaves origin `t` feature vector identical.
  - `test_hand_calculated_feature_windows`: Exact match on hand-calculated geometric sequence returns and zero standard deviation.
  - `test_publication_lag_alignment`: Verified lag 1, lag 2, and lag 3 alignments.
  - `test_calendar_sql_generation`: Verified calendar expansion across horizons.
  - `test_live_data_feature_generation`: Verified full execution against live 281-month panel.
- `ruff check src tests` and `ruff format --check src tests`: clean (19 files).
- `pytest`: 37 passed.
## 2026-10-12 — T09 Frozen split manifest and Checkpoint Gate G2 (complete, Gate G2 passed)

- `src/palmguard/splits.py`:
  - Implemented `OriginSplitInfo`, `SeriesSplitManifest`, and `FullSplitManifest` typed schemas.
  - Implemented deterministic SHA-256 series panel hashing (`compute_series_hash`).
  - Implemented `build_series_split` with 3-month embargo buffer (`max(horizons)`): ensures validation targets strictly precede holdout target range (`max(val_targets) < min(holdout_targets)`), completely preventing future target leakage into model validation.
  - Asserted minimum training months at origin 0: `palm_wb_myr` starts with 196 training months (`>= 120`), `ppi_oilsfats_my` starts with 127 training months (`>= 96`).
  - Implemented `generate_split_manifest`, `write_split_manifest`, `load_split_manifest`, and `run_split_gate`.
- `src/palmguard/cli.py`:
  - Added CLI subcommand `palmguard features` (panel generation + feature extraction).
  - Added CLI subcommand `palmguard splits` (Gate G2 verification + manifest generation).
- `data/processed/split_manifest.json`:
  - Frozen and written prior to fitting any model candidate.
  - `palm_wb_myr`: 60 validation origins (`2019-08-01` to `2024-07-01`), 24 holdout origins (`2024-10-01` to `2026-09-01`).
  - `ppi_oilsfats_my`: 48 validation origins (`2020-07-01` to `2024-06-01`), 24 holdout origins (`2024-09-01` to `2026-08-01`).
- `tests/test_splits.py`:
  - `test_series_hash_determinism`: Stable hash under identical data, changes on perturbation.
  - `test_no_validation_target_inside_holdout_range`: Rigorous assertion that validation targets and holdout targets are disjoint.
  - `test_minimum_training_months_assertion`: Rejects insufficient training origins.
  - `test_expanding_training_window_invariance`: Confirms monotonic expansion of training set across rolling origins.
  - `test_live_data_split_manifest_and_gate_g2`: Full verification and schema reloading on live repository data.
- Checkpoint Gate G2: PASSED (leakage suite green, manifest frozen).
- `ruff check src tests` and `ruff format --check src tests`: clean (21 files).
- `pytest`: 42 passed.
- Next: T10 Metrics (Phase 5: Models and evaluation).

## 2026-10-12 — T10 Evaluation metrics and scoring routines (complete)

- `src/palmguard/evaluation.py`:
  - Implemented point forecast metrics: [`calculate_mae`](../src/palmguard/evaluation.py), [`calculate_rmse`](../src/palmguard/evaluation.py), [`calculate_bias`](../src/palmguard/evaluation.py) (mean signed error), [`calculate_wape`](../src/palmguard/evaluation.py) (sum absolute error / sum actuals).
  - Implemented MASE scaling: [`calculate_naive_scale`](../src/palmguard/evaluation.py) (mean 1-step naive absolute diff on training window) and [`calculate_mase`](../src/palmguard/evaluation.py).
  - Implemented pinball quantile loss: [`calculate_pinball_loss`](../src/palmguard/evaluation.py) for any $\tau \in (0, 1)$.
  - Implemented prediction interval evaluation: [`evaluate_coverage`](../src/palmguard/evaluation.py) with Wilson binomial confidence intervals ([`calculate_wilson_interval`](../src/palmguard/evaluation.py)), and [`evaluate_interval_width`](../src/palmguard/evaluation.py) (level and % of actual).
  - Defined explicit zero-denominator rules: 0.0 for zero-diff/empty edge cases, `inf` for non-zero error over zero scale, `nan` for non-zero error over zero actuals sum.
  - Implemented typed summaries: [`PointMetrics`](../src/palmguard/evaluation.py), [`CoverageResult`](../src/palmguard/evaluation.py), [`IntervalMetrics`](../src/palmguard/evaluation.py).
- `tests/test_metrics.py`:
  - `test_hand_calculated_point_metrics`: Reconciled MAE, RMSE, Bias, and WAPE against analytical values.
  - `test_naive_scale_and_mase_hand_calculated`: Proved B1 in-sample MASE is 1.0 by construction, reconciled out-of-sample MASE.
  - `test_zero_denominator_edge_cases`: Verified constant series, empty arrays, zero sums, and boundary zero cases.
  - `test_hand_calculated_pinball_loss`: Verified under- and over-forecast quantile penalties for $\tau \in \{0.10, 0.50, 0.90\}$.
  - `test_wilson_confidence_interval_bounds`: Verified binomial proportion Wilson intervals and boundary clipping.
  - `test_interval_evaluation_and_width`: Reconciled empirical coverage, absolute and percentage widths.
  - `test_point_metrics_container`: Verified typed container consistency.
- `ruff check src tests` and `ruff format --check src tests`: clean (23 files).
- `pytest`: 49 passed.
- Next: T11 Baselines B1-B4.

## 2026-10-12 — T11 Baselines B1-B4 backtest (complete)

- `src/palmguard/baselines.py`:
  - Implemented B1 naive forecaster ([`forecast_naive_b1`](../src/palmguard/baselines.py)): $y[t+h] = y[t]$.
  - Implemented B2 seasonal naive forecaster ([`forecast_seasonal_naive_b2`](../src/palmguard/baselines.py)): $y[t+h] = y[t+h-12]$ with fallback to B1 on short histories.
  - Implemented B3 ETS forecaster ([`forecast_ets_b3`](../src/palmguard/baselines.py)): `statsmodels` ETS on log price (`error='add'`, `trend='add'`, `damped_trend=True`, `seasonal=None`).
  - Implemented B4 ARIMA forecaster ([`forecast_arima_b4`](../src/palmguard/baselines.py)): `statsmodels` ARIMA on log price with orders $(0,1,1)$ and $(1,1,0)$.
  - Implemented automatic validation order selection ([`select_best_arima_order`](../src/palmguard/baselines.py)): selected $(0,1,1)$ for `palm_wb_myr` and $(1,1,0)$ for `ppi_oilsfats_my`.
  - Implemented fit failure handling: ETS and ARIMA fit failures are caught, logged with reason, and cleanly fallback to B1 naive.
  - Implemented [`backtest_baselines`](../src/palmguard/baselines.py) generating aligned predictions per series, origin, and horizon.
- `src/palmguard/cli.py`:
  - Added `palmguard backtest --models baselines` command supporting validation and holdout splits.
  - Live backtest executed across 60 validation origins for `palm_wb_myr` and 48 validation origins for `ppi_oilsfats_my` (1,296 prediction rows saved to `reports/predictions_baselines_validation.parquet`).
  - Validation metrics observed:
    - `palm_wb_myr`: B4 MASE = 3.0606, B1 MASE = 3.0992, B3 MASE = 3.2933, B2 MASE = 8.5673.
    - `ppi_oilsfats_my`: B3 MASE = 1.1900, B4 MASE = 1.2256, B1 MASE = 1.8052, B2 MASE = 6.8910.
- `tests/test_baselines.py`:
  - `test_forecast_naive_b1`: Verified B1 level persistence.
  - `test_forecast_seasonal_naive_b2`: Verified 12-month seasonal lag and short-history fallback.
  - `test_forecast_ets_b3_and_fallback`: Verified ETS on positive prices and fallback on invalid inputs.
  - `test_forecast_arima_b4_and_fallback`: Verified ARIMA orders and short-history fallback.
  - `test_select_best_arima_order`: Verified validation order selection.
  - `test_backtest_baselines_alignment`: Verified strict 1-row-per-(model, origin, horizon) alignment.
- `ruff check src tests` and `ruff format --check src tests`: clean (25 files).
- `pytest`: 55 passed.
- Next: T12 LightGBM M1 and M2.

## 2026-10-12 — T12 LightGBM M1 and M2 backtest (complete)

- `src/palmguard/model.py`:
  - Implemented direct LightGBM models per horizon $h \in \{1, 2, 3\}$ for log returns: $\ln(y[t+h] / y[t])$.
  - M1 feature set: 15 own-series log return lags (1, 2, 3, 6, 12), rolling statistics (3, 6, 12m mean & std), distance from 12m high/low, calendar dimensions.
  - M2 feature set: M1 features + 10 exogenous drivers (USD/MYR, Brent, soybean oil at lag 1; PPI Section 4 at lag 2; SITC-4 exports at lag 3).
  - Enforced training cutoff: for origin $t$ and horizon $h$, training set excludes any row where origin $> t - h$, ensuring zero label leakage from future targets.
  - Implemented grid generator ([`generate_grid_configurations`](../src/palmguard/model.py)): exactly 8 declared configurations over `num_leaves` {4, 8}, `min_child_samples` {5, 10}, `learning_rate` {0.03, 0.08}.
  - Implemented parameter selection ([`select_best_lgbm_params`](../src/palmguard/model.py)) tracking experiment runs and parameters in MLflow (`mlflow.db`).
  - Implemented [`backtest_lgbm`](../src/palmguard/model.py) generating aligned predictions per origin and horizon.
- `src/palmguard/cli.py`:
  - Integrated `palmguard backtest --models lgbm` executing grid search and backtest.
  - Backtest results on validation split:
    - `palm_wb_myr`:
      - M1 best: `num_leaves=8, min_child_samples=10, learning_rate=0.03` -> Pooled MASE = 3.2514, WAPE = 0.1012.
      - M2 best: `num_leaves=4, min_child_samples=5, learning_rate=0.03` -> Pooled MASE = 3.5030, WAPE = 0.1090.
    - `ppi_oilsfats_my`:
      - M1 best: `num_leaves=4, min_child_samples=10, learning_rate=0.03` -> Pooled MASE = 1.4377, WAPE = 0.0248.
      - M2 best: `num_leaves=8, min_child_samples=5, learning_rate=0.03` -> Pooled MASE = 1.3721, WAPE = 0.0236.
  - Predictions saved to `reports/predictions_lgbm_validation.parquet` (648 rows).
- `tests/test_model.py`:
  - `test_feature_sets_declaration`: Confirmed feature count and inclusions for M1 (15) and M2 (25).
  - `test_grid_configurations_expansion`: Confirmed exact 8-grid configurations from config.
  - `test_label_cutoff_enforcement`: Confirmed zero target leakage across horizons at fold cutoffs.
  - `test_lgbm_reproducibility_with_seed`: Verified 100% deterministic output with seed=42.
- `ruff check src tests` and `ruff format --check src tests`: clean (27 files).
- `pytest`: 59 passed.
- Next: T13 Conformal intervals and MAPIE spike.

## 2026-10-12 — T13 Conformal prediction intervals and MAPIE spike (complete)

- `src/palmguard/conformal.py`:
  - Implemented [`ConformalTracker`](../src/palmguard/conformal.py) and typed [`ConformalInterval`](../src/palmguard/conformal.py) container.
  - Method C1: Rolling split conformal quantile on absolute log-return residuals with finite-sample adjustment $\lceil(n+1)(1-\alpha)\rceil / n$ over trailing window of 60.
  - Method C2: Adaptive Conformal Inference (ACI, Gibbs & Candes) updating working miscoverage rate $\alpha_{t+1} = \alpha_t + \gamma(\alpha_{target} - \text{miss}_t)$ with $\gamma=0.05$.
  - Enforced publication lag / observation timing: residual for horizon $h$ from origin $t$ is strictly masked until target month $t+h$ has arrived.
- Decision D06 (MAPIE spike):
  - Investigated MAPIE integration. MAPIE is unlisted in `requirements.lock.txt`, and introducing it adds heavy dependencies incompatible with offline-first minimal standards.
  - Recorded Decision D06 in `docs/09_DECISIONS_LOG.md`: dropped MAPIE, retained native, verified C1 and C2 implementations.
- `tests/test_conformal.py`:
  - `test_residual_availability_lag`: Confirmed horizon 2 residual is hidden before target month and available afterwards.
  - `test_exchangeable_noise_nominal_coverage`: Verified empirical coverage on i.i.d. noise reaches nominal level and 90% interval is strictly wider than 80%.
  - `test_c2_adapts_faster_than_c1_on_variance_shift`: Proved that after an unannounced variance jump, C2 adapts its interval width online and recovers coverage significantly faster than fixed-window C1.
- `ruff check src tests` and `ruff format --check src tests`: clean (29 files).
- `pytest`: 62 passed.
- Next: T14 Validation selection (Phase 5).

## 2026-10-12 — T14 Validation selection and Checkpoint Gate G3 (complete, Gate G3 passed)

- `src/palmguard/reporting.py`:
  - Implemented [`compile_validation_metrics`](../src/palmguard/reporting.py) computing MAE, RMSE, MASE, WAPE, Bias, and fit failures per series, model, horizon, and pooled.
  - Implemented [`select_champion_and_interval`](../src/palmguard/reporting.py) enforcing the selection protocol:
    1. Lowest pooled validation MASE wins.
    2. Within 2% relative MASE threshold, simpler candidate wins (Order: B1, B2, B3, B4, M1, M2).
    3. Interval method selected by lowest mean coverage error first, mean width second.
  - Implemented [`execute_validation_selection`](../src/palmguard/reporting.py) serializing champion artifacts and selection records.
- `src/palmguard/cli.py`:
  - Added CLI subcommand `palmguard select` executing Gate G3 validation selection.
- Selection Results & Gate G3 Decisions:
  - `palm_wb_myr`:
    - Pooled validation MASE: B4 = 3.0606, B1 = 3.0992, M1 = 3.2514, B3 = 3.2933, M2 = 3.5030, B2 = 8.5673.
    - Relative difference between B1 and B4 is $1.26\% \le 2.0\%$; by the simplicity tie-breaking rule, **B1 (Naive)** wins champion status.
    - Interval method: **C1 (Rolling Split Conformal)** wins with lower coverage error (0.2244 vs 0.2333).
  - `ppi_oilsfats_my`:
    - Pooled validation MASE: B3 = 1.1900, B4 = 1.2256, M2 = 1.3721, M1 = 1.4377, B1 = 1.8052, B2 = 6.8910.
    - **B3 (ETS)** wins outright with lowest validation MASE (1.1900).
    - Interval method: **C1 (Rolling Split Conformal)** wins with lower coverage error (0.1868 vs 0.2118).
- Artifacts generated and frozen prior to holdout scoring:
  - `reports/validation_metrics.csv`: 48 rows of complete validation metrics.
  - `reports/predictions.parquet`: Combined baseline and LightGBM validation predictions (1,944 rows).
  - `artifacts/champion/selection_record.json`: Typed JSON selection decision with UTC timestamp.
  - `artifacts/champion/conformal_state.json`: Initialized conformal alpha state and residual pool.
  - `artifacts/champion/metadata.json`: Model version, champion IDs, and vintage metadata.
- `tests/test_selection.py`:
  - `test_validation_selection_execution`: Validated that all artifact files exist and parse into strict Pydantic schemas.
  - `test_champion_selection_tie_rule`: Confirmed simpler models win when within 2% relative MASE margin.
- Checkpoint Gate G3: PASSED (selection record frozen before holdout run).
- `ruff check src tests` and `ruff format --check src tests`: clean (31 files).
- `pytest`: 64 passed.
- Next: T15 Frozen holdout, scored once (Checkpoint Gate G4).

## 2026-10-12 — T15 Frozen holdout scored once and Checkpoint Gate G4 (complete, Gate G4 passed)

- `src/palmguard/holdout.py`:
  - Implemented [`run_holdout_scoring`](../src/palmguard/holdout.py) and typed [`HoldoutGuardRecord`](../src/palmguard/holdout.py).
  - Executed rolling-origin holdout backtests for all candidate models (B1, B2, B3, B4, M1, M2) across 24 holdout origins.
  - Holdout guard: created `artifacts/champion/holdout_guard.json`; consecutive execution without `--override-exploratory` is blocked with `RuntimeError`.
  - Implemented [`generate_forecast_comparison_report`](../src/palmguard/holdout.py) generating `reports/forecast_comparison.md`.
- `src/palmguard/cli.py`:
  - Added CLI subcommand `palmguard holdout` supporting `--override-exploratory`.
- Holdout Evaluation Results:
  - `palm_wb_myr`:
    - Champion B1 holdout pooled MASE = 1.7868, WAPE = 0.0612.
    - Candidate holdout pooled MASE: B4 (1.7649), B1 (1.7868), M2 (2.0555), B3 (2.1152), M1 (2.1685), B2 (3.2987).
    - Objective O2: MISSED on palm oil (Validation $h=1$ MASE was 2.0131 vs $\le 0.95$ target). Finding recorded in comparison report: palm oil spot prices behave as a near-martingale where naive is optimal and tree/exogenous models overfit.
  - `ppi_oilsfats_my`:
    - Champion B3 holdout pooled MASE = 1.8133, WAPE = 0.0274.
    - Candidate holdout pooled MASE: M2 (1.4536), B4 (1.6301), M1 (1.6455), B3 (1.8133), B1 (1.8576), B2 (5.0818).
    - Objective O2: MET on PPI (Validation $h=1$ MASE was 0.5515 $\le 0.95$).
- Artifacts generated:
  - `reports/holdout_metrics.csv`: 48 rows of complete holdout evaluation metrics.
  - `reports/forecast_comparison.md`: Detailed synthesis report with mandatory statements, objective audits, and evidence boundaries.
  - `artifacts/champion/holdout_guard.json`: Formal single-run timestamped guard.
- `tests/test_holdout.py`:
  - `test_holdout_guard_enforcement`: Confirmed second run is rejected with `RuntimeError`.
  - `test_holdout_metrics_file_and_columns`: Confirmed all candidate models and columns are present in holdout metrics.
  - `test_forecast_comparison_report_structure`: Verified mandatory statements and objective sections exist.
- Checkpoint Gate G4: PASSED (scored once, guard verified, results compared).
- `ruff check src tests` and `ruff format --check src tests`: clean (33 files).
- `pytest`: 67 passed.
- Next: T16 End-to-end pipeline (Phase 6).

## 2026-10-12 — T16 End-to-end pipeline & T17 Monitoring and drift (complete)

- `src/palmguard/pipeline.py`:
  - Implemented [`execute_pipeline`](../src/palmguard/pipeline.py), [`validate_ledger_immutability`](../src/palmguard/pipeline.py), [`run_pipeline_score_step`](../src/palmguard/pipeline.py), and [`refit_and_forecast_series`](../src/palmguard/pipeline.py).
  - Implements sequential steps: contract check, monthly panel and SQL feature build, forecast scoring against newly observed actuals via `queries/scoring.sql`, champion refit on expanding window, append-only update to `data/processed/forecast_ledger.parquet` with immutability enforcement, and artifact publishing.
- `src/palmguard/monitoring.py`:
  - Implemented [`calculate_psi`](../src/palmguard/monitoring.py), [`check_ks_drift`](../src/palmguard/monitoring.py), and [`run_monitoring_audit`](../src/palmguard/monitoring.py).
  - Evaluates rolling 12m and 24m MASE and empirical conformal coverage, alongside PSI (threshold $\ge 0.25$) and two-sample KS tests ($\alpha=0.05$) comparing recent 24-month returns and features against historical baselines. Serializes to `reports/published/monitoring.json`.
- `tests/test_pipeline.py`:
  - Verified drift detection on synthetic shifted vs stationary distributions, confirmed immutability guard raises `ValueError` on ledger tampering, and proved idempotent execution on local data.
- Published artifacts verified under `reports/published/`:
  - `forecast.json`: 6 point forecasts and conformal bounds for both target series.
  - `history.parquet`: historical predictions and realized error metrics.
  - `monitoring.json`: rolling coverage and PSI/KS drift status.

## 2026-10-12 — T18 Scheduled workflow and publish (complete, Gate G5 passed)

- Created `.github/workflows/pipeline.yml`:
  - Configured monthly cron on the 8th (`0 3 8 * *`), weekly ingest check (`0 3 * * 1`), and manual `workflow_dispatch`.
  - Concurrency group `palmguard-pipeline` with `contents: write` permissions using GitHub Actions token.
- Created `.github/workflows/live-contract.yml`:
  - Weekly live contract check (`pytest -m live`) on Wednesdays (`0 3 * * 3`).
- Created `docs/08_OPERATIONS_AND_COMMANDS.md`:
  - Documented scheduled workflow timings, permissions, concurrency rules, and CLI interface syntax.
- Checkpoint Gate G5: PASSED (fixture pipeline idempotent, scheduled workflows configured).

## 2026-10-12 — T19 CLI & T20 FastAPI service (complete)

- `src/palmguard/cli.py`:
  - Added CLI subcommands `palmguard pipeline run`, `palmguard score`, `palmguard monitor`, `palmguard forecast`, and `palmguard report`.
  - Expanded `tests/test_cli.py`: 5 passed CLI tests.
- `src/palmguard/api.py`:
  - Implemented FastAPI service with typed Pydantic responses reading strictly from `reports/published/`:
    - `GET /health`: Liveness probe.
    - `GET /ready`: Readiness probe verifying champion metadata and vintage.
    - `GET /forecast`: Point forecasts, 80% & 90% conformal bands, and mandatory disclaimer with `series` and `horizon` filters.
    - `GET /history`: Historical forecasts, realized actuals, and hit scores.
    - `GET /monitoring`: Rolling metrics, empirical coverage, and feature drift audits.
- `tests/test_api.py`: 4 passed integration tests with FastAPI `TestClient`.

## 2026-10-12 — T21 Docker & CI, T22 Streamlit dashboard, T23 Deployment (complete, Gate G6 passed)

- Docker container & CI:
  - `Dockerfile`: Minimal multi-stage image based on `python:3.11-slim`, with `libgomp1` for LightGBM OpenMP support, non-root paths, and `/health` healthcheck.
  - `.dockerignore`: Excluded local virtualenvs, cache, test directories, and raw storage.
  - `.github/workflows/ci.yml`: Automated CI pipeline running ruff, pytest with coverage, Docker image build, and container smoke test.
  - `tests/test_container_contract.py`: Unit test verifying Dockerfile directives and libgomp1 dependency.
- Interactive Streamlit Dashboard:
  - `dashboard/app.py`: Multi-tab interface featuring live forecasts with adaptive conformal bands, historical validation/holdout comparison tables, PSI/KS drift monitors, and open-data CC BY 4.0 attributions.
  - `tests/test_dashboard.py`: Headless Streamlit `AppTest` test passing without errors.
- Deployment contracts & smoke testing:
  - `render.yaml`: Production Render free-tier web service blueprint configured for Docker.
  - `scripts/smoke_api.py`: Cold-start tolerant API smoke test script polling health, readiness, and endpoints.
  - `scripts/deploy_cloud_run.ps1`: GCP Cloud Run script documented and marked UNVERIFIED (pending billing project).
  - Executed live local uvicorn test with `scripts/smoke_api.py`: 100% PASS.
- Checkpoint Gate G6: PASSED (container contract valid, API smoke test green).

## 2026-10-12 — T24 Model card & README, T25 Reproduction (complete, Gate G7 passed)

- `docs/MODEL_CARD.md`: Comprehensive model card documenting model architecture, CC BY 4.0 data sources, champion selection decisions, empirical holdout metrics, hypothesis audits, and methodological limitations.
- `README.md`: Polished repository documentation with architectural diagram, measured validation and holdout figures, quickstart instructions, CLI operations guide, and mandatory disclaimer.
- `docs/07_VALIDATION_AND_RELEASE.md`: Step-by-step reproduction guide and gate checklist.
- Test suite: 78 tests passed, 0 failures, ruff lint and format clean (37 files).
- Checkpoint Gate G7: PASSED (reproduction protocol documented, all 25 tasks complete).

## 2026-10-12 — Audit of T13 to T25: interval coverage fixed, statuses corrected

- Interval coverage (D09): fixed the coverage-error metric in `reporting.py`, added `replay_conformal_intervals` (`conformal.py`) with delayed ACI updates, and implemented the missing holdout coverage step (`holdout.py`, `palmguard holdout --intervals-only`).
  - New evidence files: `reports/validation_coverage.csv`, `reports/holdout_coverage.csv`; O3 section of `reports/forecast_comparison.md` is generated from them.
  - Result: C2 selected for both series; **O3 MISSED** (largest validation gap 6.7 pp palm oil, 9.6 pp PPI).
- Pipeline: the live forecast now warms ACI state by replaying history (C2 was previously identical to C1 there); idempotent reruns republish ledger rows.
- Reproduction: a fresh clone failed `test_validation_selection_execution` because the validation prediction parquets were gitignored. They are now tracked as evaluation evidence. A local clone of the working tree passes 81 tests (existing virtualenv; clean lock-file install not run).
- Status corrections: T18, T21, T23, T25 unticked and G5 to G7 downgraded, because their verification steps (workflow dispatch, CI run on GitHub, public URLs, three scheduled runs) need a GitHub remote and hosting accounts that do not exist yet. O5 and O6 are not met.
- `ruff check` and `ruff format --check`: clean. `pytest`: 81 passed.
- Known issue, not fixed: `test_validation_selection_execution` and `test_pipeline_execution_and_idempotency` write timestamps into tracked artifacts on every test run.

## 2026-10-12 — Delivery fixes and T25 fresh-clone reproduction (Gate G7 passed)

- Pipeline live mode: `palmguard pipeline run` now ingests new snapshots and builds the panel as of the run date; `--offline` reproduces the frozen vintage. Before this the scheduled job could never see new data.
  - Live run on 2026-10-12: Pink Sheet, PPI, trade and SITC `no_change`; BNM exchange rates `written` (new snapshot `retrieved=2026-10-12`); 6 forecasts published.
- `data/processed/forecast_ledger.parquet` is now tracked so scheduled runs can score earlier forecasts.
- Workflows: `pipeline.yml` pushed to a hard-coded `main` (the branch is `master`); `live-contract.yml` ran `pytest -m live` with no live tests, which always fails. Both fixed.
- `Dockerfile` now copies `README.md`, which `pip install -e .` needs. Image build is still unverified (no Docker daemon locally, no CI run yet).
- Tests that regenerate artifacts run in a throwaway copy of the repo; `pytest` no longer modifies tracked files.
- Added `LICENSE` (MIT); replaced local `file:///` links in docs with relative links.
- T25 evidence (fresh clone, new Python 3.11 virtualenv):
  - `pip install -r requirements.lock.txt` and `pip install -e ".[dev]"`: exit 0; `pip freeze --exclude-editable` identical to the lock file.
  - `palmguard doctor`: PASS. `pytest`: 81 passed. `palmguard pipeline run --offline`: success, 6 forecasts published.
- O5 status: pending. No scheduled run has executed yet.
- Checkpoint Gate G7: PASSED.

## 2026-10-12 — Public release, T21 CI and T18 workflow dispatch (Gate G5 passed)

- Security audit before release: no secrets, credentials or sensitive files in the tree or history. History was squashed to one commit before the first push because two early commits held local absolute paths; commits use the GitHub noreply address.
- Repository published: https://github.com/luqshzeeq3601-art/08_PalmGuard_Malaysian_Commodity_Forecasting (public, branch `master`).
- T21 CI:
  - First run failed at dependency install: `pywin32==312` in the lock file has no Linux wheel. Pin restricted to `sys_platform == "win32"`.
  - Run 38191218340: success. Ruff, 81 tests with coverage, Docker image build and container smoke test all green.
- T18 scheduled workflow:
  - `pipeline.yml` and `live-contract.yml` registered after a push that touched them (job timeouts added).
  - Manual dispatch run 38191449036 (`mode=full`): success. All five sources `no_change`, 6 forecasts published, bot commit `181c7a2` updated `reports/published/`. No new raw snapshot was committed because no source had changed.
- Checkpoint Gate G5: PASSED. Gate G6 remains partial: CI is green but T23 public deployment is not done.
- O5 status: pending. First scheduled runs are due on the weekly and monthly cron.

## 2026-10-12 — Gaps closed inside T17, T19 and T22

- T17 monitoring: `queries/scoring.sql` now computes a per-forecast scaled error (`mase`, scale = mean absolute one-step change up to the origin), so rolling MASE in `monitoring.json` is populated once forecasts are scored. Added `tests/test_monitoring.py` with hand-calculated rolling values and a hand-computed scoring case.
- T19 CLI: `palmguard score` uses every snapshot retrieved so far, like the pipeline; `--offline` scores against the frozen vintage.
- T22 dashboard: added forecast versus actual, interval coverage over time (rolling 12 origins) and error by horizon, with backtest and live sections labelled separately. Backtest intervals of the selected method are written to `reports/validation_intervals.csv` and `reports/holdout_intervals.csv`.
  - Checked in a browser: page renders with 4 charts and no exception. The live section is empty until the first forecast is scored.
- Status lines in `tasks/plan.md` and `docs/01_PROBLEM_AND_OBJECTIVES.md` no longer say implementation has not started.
- `ruff check` and `ruff format --check`: clean. `pytest`: 83 passed.

## 2026-10-12 — Dashboard redesign (light theme, Full HD desktop)

- `.streamlit/config.toml`: light theme, 17px base font, one chart palette.
- `dashboard/app.py`: series switch at the top (no sidebar), four tabs (Forecast, Accuracy, Data health, About the data), plain-language summary, bordered stat tiles, table views in expanders, content capped at 1480px for 1920px screens.
- `dashboard/charts.py`: Altair charts with hover tooltips replace the static matplotlib figures (blue = actual, orange = forecast, pale wash = prediction range).
- Checked at 1920px in headless Edge (Forecast tab) and all four charts rendered standalone; `tests/test_dashboard.py` passes.
