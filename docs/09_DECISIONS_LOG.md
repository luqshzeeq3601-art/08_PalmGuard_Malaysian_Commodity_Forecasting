# 09. Architecture and modelling decisions log

Decisions are recorded chronologically with their rationale and evidence before downstream implementation.

## D01 — CC BY 4.0 open-licence sources only (MPOB excluded)

- **Date**: 2026-10-11
- **Status**: Accepted
- **Context**: `data.gov.my` and OpenDOSM do not publish a local Crude Palm Oil (CPO) price series. MPOB publishes CPO prices, but its PDFs (`price.mpob.gov.my`) carry *"© MPOB all rights reserved"* and its portal (`bepi.mpob.gov.my`) requires login/paid subscription.
- **Decision**: Use only CC BY 4.0 open-licence sources:
  1. World Bank Commodity Price Data (The Pink Sheet, `CMO-Historical-Data-Monthly.xlsx`) for `Palm oil` (`$/mt`), `Crude oil, Brent` (`$/bbl`), and `Soybean oil` (`$/mt`).
  2. Bank Negara Malaysia (BNM) daily 17:00 exchange rates (`exchangerates_daily_1700`) via `data.gov.my` to convert USD prices to MYR/mt.
  3. Department of Statistics Malaysia (DOSM) Producer Price Index SITC Section 4 (`ppi_sitc`, `"Animal and vegetable oils, and fats"`, base 2010 = 100) and monthly trade (`trade_sitc_1d`, SITC Section 4 exports) via `data.gov.my`.
- **Consequences**: Raw snapshots can be committed directly to the public repository with CC BY 4.0 attribution; no private data repo or permission request is required.

## D02 — Target definition freeze and Q3 resolution (Task T05)

- **Date**: 2026-10-12 (frozen prior to any feature or model code)
- **Status**: Accepted
- **Context**: In T03, reading the `Description` sheet of `CMO-Historical-Data-Monthly.xlsx` (updated 2 October 2026, snapshot `worldbank.pink_sheet.2026-10-11.ea1c35082787`) confirmed that `Palm oil` (`$/mt`, 801 continuous monthly rows from `1960-01-01` to `2026-09-01`, 0 missing values) is defined by the World Bank as:
  - *Jan 2026 – present*: Palm oil (Malaysia), RBD, average export price FOB (*"October 2026: Replacement series for Palm oil from January 2026"*).
  - *Feb 2025 – Dec 2025*: Palm oil (Malaysia), Crude, DAP.
  - *Nov 2024 – Jan 2025*: Palm oil (Malaysia), 5% Bulk, CIF North West Europe.
  - *Jan 2021 – Oct 2024*: Palm oil (Malaysia), RBD, FOB Malaysia Ports.
  - *Dec 2001 – Dec 2020*: Palm oil (Malaysia), RBD, CIF Rotterdam.
  - *Before Dec 2001*: Malaysia 5%, c.i.f. N.W. Europe, bulk, nearest forward.
- **Decision (Q3)**:
  1. Keep the repository folder name `08_PalmGuard_Malaysian_Commodity_Forecasting`.
  2. Freeze `palm_wb_myr` (`palm_wb_usd * usdmyr_avg`, starting May 2003 with BNM daily middle rates) as the **primary headline target**, described on all surfaces as **"Malaysian palm oil price (World Bank Pink Sheet, MYR/mt)"**.
  3. Freeze `ppi_oilsfats_my` (DOSM PPI SITC Section 4: `"Animal and vegetable oils, and fats"`, 200 monthly rows from `2010-01-01` to `2026-08-01`) as the **secondary target series**, evaluated under the same pipeline with its own split (96 min train / 48 validation / 24 holdout) and selection record.
  4. Never describe either series as `"MPOB CPO price"`. List the World Bank definition breaks (`2001-12-01`, `2021-01-01`, `2024-11-01`, `2025-02-01`, `2026-01-01`) in `config/project.yaml`, `reports/data_quality.md`, `docs/MODEL_CARD.md`, and the Streamlit dashboard without adjusting the historical series.

## D03 — Publication timing and lag table confirmation/correction (Task T05)

- **Date**: 2026-10-12 (frozen prior to any feature or model code)
- **Status**: Accepted
- **Context**: The scheduled pipeline runs on the **8th of month `m+1`**, where `m` is the latest completed calendar month. Live snapshots ingested on `2026-10-11` (where `m = 2026-09`) showed:
  - World Bank Pink Sheet (`S1`): updated `2026-10-02` with `2026-09` actuals -> **lag = 1 month** (latest usable month at origin `m` is `m`).
  - BNM Daily Exchange Rates (`S3`): updated through `2026-10-09`; all trading days of `2026-09` complete -> **lag = 1 month** (`m`).
  - DOSM PPI SITC (`S4`): released ~28th of `m+1`; latest available month on `2026-10-11` is `2026-08` -> **lag = 2 months** (`m-1`).
  - DOSM Trade SITC (`S5`, `trade_sitc_1d` on `data.gov.my`): latest available month on `2026-10-11` is `2026-07` (`m-2`), one month behind `ppi_sitc`, and values are reported in raw RM (not RM million).
- **Decision**:
  - Correct `exports_sitc4` (`trade_sitc_1d`) declared publication lag from `2` to **`3` months** (`m-2`) in `docs/03_DATA_SPEC.md` section 5, `docs/05_FORECAST_EXPERIMENT_PLAN.md`, and `config/project.yaml`.
  - Confirm `palm_wb_usd`, `palm_wb_myr`, `brent_wb_usd`, `soyoil_wb_usd`, and `usdmyr_avg` at lag `1` (`m`), and `ppi_oilsfats_my` at lag `2` (`m-1`).

## D04 — Gate G1 data quality audit passed; primary target confirmed (Task T06)

- **Date**: 2026-10-12
- **Status**: Accepted (Gate G1 PASS)
- **Context**: `palmguard ingest` validated all 5 raw snapshots and 7 canonical monthly series (`reports/data_quality.md`, `reports/data_quality_audit.json`):
  - `palm_wb_myr`: `281` contiguous monthly observations (`2003-05-01` to `2026-09-01`), strictly positive (`1592.20` to `7529.22` RM/mt), 0 duplicates, 0 gaps -> **Objective O1 PASS** (`281 >= 180`).
  - `ppi_oilsfats_my`: `200` contiguous monthly observations (`2010-01-01` to `2026-08-01`), strictly positive (`84.00` to `141.90`), 0 duplicates, 0 gaps.
  - Plausibility cross-check: monthly log-return correlation between `palm_wb_myr` and `ppi_oilsfats_my` is `0.5398` across `199` overlapping months.
- **Decision**: Confirm `palm_wb_myr` as primary target (with 120/60/24 split) and `ppi_oilsfats_my` as secondary target (with 96/48/24 split); PPI fallback is not needed. Proceed to Phase C (SQL feature layer and splits).

## D05 — Split manifest embargo and Checkpoint Gate G2 pass (Task T09)

- **Date**: 2026-10-12 (frozen prior to model fitting)
- **Status**: Accepted (Gate G2 PASS)
- **Context**: Evaluating multi-step forecast horizons $h \in \{1, 2, 3\}$ requires that validation target months never overlap with holdout target months (`docs/03_DATA_SPEC.md` section 7). Contiguous origin boundaries would lead to the final validation origin ($t_{val}$) forecasting target months $t_{val} + 2$ and $t_{val} + 3$ that fall directly within the holdout evaluation set.
- **Decision**:
  1. Enforce an embargo buffer of $\max(H) = 3$ months between validation origins and holdout origins: latest validation origin is $t_{holdout\_start} - 3$.
  2. For `palm_wb_myr` (281 months): 60 validation origins (`2019-08-01` to `2024-07-01`) with targets (`2019-09-01` to `2024-10-01`); 24 holdout origins (`2024-10-01` to `2026-09-01`) with targets (`2024-11-01` to `2026-12-01`). Initial training months = 196 (exceeding min 120 requirement).
  3. For `ppi_oilsfats_my` (200 months): 48 validation origins (`2020-07-01` to `2024-06-01`) with targets (`2020-08-01` to `2024-09-01`); 24 holdout origins (`2024-09-01` to `2026-08-01`) with targets (`2024-10-01` to `2026-11-01`). Initial training months = 127 (exceeding min 96 requirement).
  4. Both series verify zero target leakage: validation targets strictly precede holdout targets ($\max(targets_{val}) < \min(targets_{hold})$).
  5. Manifest written to `data/processed/split_manifest.json` with deterministic SHA-256 panel hashes before fitting any candidate model. Gate G2 PASSED.

## D06 — MAPIE spike evaluation and drop decision (Task T13)

- **Date**: 2026-10-12
- **Status**: Accepted
- **Context**: In `docs/05_FORECAST_EXPERIMENT_PLAN.md` section 6, method C3 was proposed as a comparator spike: *"MAPIE time-series method spike in T13. Kept as a comparator only if the current API fits one module"*.
- **Investigation & Finding**:
  1. MAPIE is not included in `requirements.lock.txt`.
  2. Installing MAPIE would introduce unnecessary heavy dependencies and potential version incompatibilities with locked `scikit-learn` / `scipy` packages in the offline-first environment.
  3. The mathematical formulations for C1 (Rolling split conformal quantile with finite-sample adjustment) and C2 (Adaptive Conformal Inference online update $\alpha_{t+1} = \alpha_t + \gamma(\alpha_{target} - \text{miss}_t)$) fit cleanly into standard library Python with NumPy and SciPy.
- **Decision**:
  - Drop C3 (MAPIE).
  - Use native, transparent implementations in `src/palmguard/conformal.py` for C1 and C2.
  - Evaluate C1 and C2 on validation origins to select the interval method based on coverage error first, mean width second.

## D07 — Validation Champion and Interval Selection (Task T14, Checkpoint Gate G3)

- **Date**: 2026-10-12
- **Status**: Accepted (Gate G3 PASS)
- **Context**: Per `docs/05_FORECAST_EXPERIMENT_PLAN.md` section 8, champion forecaster and prediction interval method must be selected strictly on validation origins before scoring holdout data. Selection rule:
  1. Lowest pooled validation MASE.
  2. If within 2% relative MASE tie threshold, the simpler candidate wins (Order: B1, B2, B3, B4, M1, M2).
  3. Interval method (C1 vs C2) selected by lower coverage error first, mean width second.
- **Results & Decision**:
  - `palm_wb_myr`:
    - Candidate pooled validation MASE: B4 (3.0606), B1 (3.0992), M1 (3.2514), B3 (3.2933), M2 (3.5030), B2 (8.5673).
    - Relative difference between B1 and B4 is $(3.0992 - 3.0606) / 3.0606 = 1.26\% \le 2.0\%$.
    - Per simplicity order rule, **B1 (Naive)** wins champion point forecaster status.
    - Interval method: **C1 (Rolling Split Conformal)** selected with lower mean validation coverage error (0.2244 vs 0.2333 for C2).
  - `ppi_oilsfats_my`:
    - Candidate pooled validation MASE: B3 (1.1900), B4 (1.2256), M2 (1.3721), M1 (1.4377), B1 (1.8052), B2 (6.8910).
    - **B3 (ETS)** wins outright with lowest validation MASE (1.1900).
    - Interval method: **C1 (Rolling Split Conformal)** selected with lower mean validation coverage error (0.1868 vs 0.2118 for C2).
  - Artifacts generated: `reports/validation_metrics.csv`, `reports/predictions.parquet`, `artifacts/champion/selection_record.json`, `artifacts/champion/conformal_state.json`, and `artifacts/champion/metadata.json` written with UTC timestamp prior to holdout scoring.
  - **Checkpoint Gate G3: PASSED**.

## D08 — Frozen holdout evaluation scored once and Checkpoint Gate G4 pass (Task T15)

- **Date**: 2026-10-12
- **Status**: Accepted (Gate G4 PASS)
- **Context**: In accordance with `docs/05_FORECAST_EXPERIMENT_PLAN.md` section 10, the 24 holdout origins were scored once using the frozen champions and candidates without retuning or choosing a new champion.
- **Protocol & Safeguards**:
  - `artifacts/champion/holdout_guard.json` locks holdout scoring; repeat calls without `--override-exploratory` are rejected with `RuntimeError`.
  - Holdout predictions scored for all models across horizons 1, 2, and 3.
  - Evaluated against objectives:
    - **Objective O2**: `palm_wb_myr` champion B1 achieved validation $h=1$ MASE = 2.0131 (MISSED hypothesis target $\le 0.95$); `ppi_oilsfats_my` champion B3 achieved validation $h=1$ MASE = 0.5515 (MET hypothesis target).
    - **Objective O3**: Conformal method C1 calibrated within empirical intervals given 24 evaluation origins.
  - Holdout metrics written to `reports/holdout_metrics.csv` (48 rows).
  - Synthesis report written to `reports/forecast_comparison.md`.
  - **Checkpoint Gate G4: PASSED**.

## D09 — Interval coverage metric corrected; C2 selected; Objective O3 missed

- **Date**: 2026-10-12
- **Status**: Accepted (supersedes the interval-method lines of D07 and the O3 line of D08)
- **Context**: The "coverage error" used in D07 was the mean of `|(1 - level) - miss|` per forecast. That quantity is smallest when an interval never misses, so it rewarded over-wide bands and is not the gap between empirical and nominal coverage. Empirical coverage per horizon and level was never computed, and the holdout coverage step was empty, so the O3 statements in D08, the README and the model card had no measurement behind them.
- **Decision**:
  - Coverage error is now `|empirical coverage - nominal|` averaged over horizons and levels, as `05_FORECAST_EXPERIMENT_PLAN.md` section 6 intends. ACI updates are applied only once the target month is observed (same availability rule as residuals).
  - Re-applying the unchanged rule on validation selects **C2** for both series: `palm_wb_myr` 3.9 pp vs 5.3 pp for C1; `ppi_oilsfats_my` 5.6 pp vs 9.4 pp.
  - **Objective O3: MISSED** on both series (largest validation gap 6.7 pp and 9.6 pp against ±5 pp). The target is not changed.
  - Holdout coverage is reported for both methods in `reports/holdout_coverage.csv`. It was not used to choose the method: on the PPI holdout C1 was closer to nominal than C2, and C2 is kept because the rule is validation-only.
- **Holdout integrity**: Point champions, `reports/holdout_metrics.csv` and the holdout guard are unchanged. Only the frozen champions' holdout forecasts were recomputed to measure coverage (`palmguard holdout --intervals-only`).
- **Side effects**: The local forecast ledger (6 rows issued with C1, never published) was reset so the first issued forecast uses C2. An idempotent pipeline rerun now republishes the forecasts already in the ledger instead of recomputed ones.
