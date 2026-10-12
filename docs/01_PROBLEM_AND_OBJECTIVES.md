# 01. Problem and objectives

Status: DRAFT, 2026-10-11. No implementation exists yet.

## 1. Problem

Malaysian crude palm oil (CPO) prices move plantation revenue, refinery margins and procurement budgets. A planner needs a short-horizon price view with an honest statement of uncertainty, refreshed as new official figures are published.

PalmGuard forecasts a monthly palm oil price in ringgit one, two and three months ahead, attaches prediction intervals, and keeps a public record of how past forecasts compared with the published actuals.

MPOB's own CPO prices are copyright-reserved, so PalmGuard uses open-licence series only: the World Bank palm oil benchmark converted to MYR, and DOSM's producer price index for oils and fats. Neither is the MPOB local delivered CPO price, and the project does not describe them as such.

## 2. Why this project exists in the portfolio

DemandGuard (project 3) already shows retail SKU forecasting and MILP reorder optimisation on UK data. PalmGuard must show different skills on Malaysian data:

1. API ingestion with immutable, dated raw snapshots.
2. A SQL feature layer in DuckDB with tests for future leakage.
3. A scheduled pipeline that ingests, re-forecasts, scores last period's forecast and publishes.
4. Prediction intervals from conformal methods, with coverage measured.
5. A live public deployment.

Audience: hiring teams for data science roles in Kuala Lumpur (for example Golden Agri-Resources, DKSH, Mattel, AirAsia) that ask for forecasting, Python plus SQL and deployment.

## 3. Forecast definition

| Item | Definition |
| --- | --- |
| Target | World Bank Pink Sheet palm oil price (USD/tonne, monthly average) converted to RM/tonne with the monthly mean BNM USD/MYR rate |
| Target definition | Exact benchmark (crude or refined, delivery basis) confirmed from the file's notes in T03 and frozen before modelling |
| Second series | DOSM Producer Price Index, SITC section 4 "Animal and vegetable oils, and fats" (2010 = 100), via the data.gov.my API |
| Horizons | 1, 2 and 3 months ahead |
| Origin | The 8th of each month, after the previous month's Pink Sheet is published |
| Output | Point forecast plus 80% and 90% prediction intervals per horizon |

## 4. Objectives and success targets

Targets are fixed here, before modelling. They are not changed after results are seen.

| ID | Objective | Target |
| --- | --- | --- |
| O1 | Usable history | At least 180 gap-free monthly observations; all data contracts pass |
| O2 | Point accuracy (hypothesis) | Champion MASE ≤ 0.95 at h=1 on validation. If no model beats naive, naive is the champion and the README says so |
| O3 | Interval calibration | Validation coverage within ±5 percentage points of nominal at each horizon, for 80% and 90% |
| O4 | No leakage | All future-mutation, publication-lag and vintage tests pass |
| O5 | Working schedule | Three consecutive scheduled pipeline runs succeed and score a forecast |
| O6 | Public deployment | Public API and dashboard URLs pass the smoke test |

Commodity prices are close to a random walk. A result where LightGBM does not beat the naive forecast is a valid outcome and is reported plainly. The frozen holdout is scored once and never used for retuning.

## 5. Non-goals

- Daily prices, futures prices or intraday data.
- Trading signals, hedging advice or any estimate of financial benefit.
- Production, stock or export volume forecasting.
- A paid cloud deployment. GCP Cloud Run is an optional, unverified script.

## 6. Disclaimer

PalmGuard is a forecasting demonstrator. It is not trading, investment or procurement advice. No financial benefit was measured. Interval coverage is measured on historical data and is not guaranteed for future months.

## 7. Constraints

- CPU only, monthly data of a few hundred rows.
- Free services only: GitHub Actions, Render free tier, Streamlit Community Cloud.
- CC BY 4.0 sources only, so no permission is needed; attribution is required (see 03_DATA_SPEC.md section 2).
