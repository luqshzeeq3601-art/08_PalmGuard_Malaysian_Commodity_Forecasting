# Model Card: PalmGuard Malaysian Commodity Forecasting Engine

**Model Architecture & Version**: `PalmGuard v0.1.0` (Production Demonstrator)  
**Date of Release**: October 2026  
**License**: MIT (Code) / CC BY 4.0 (Data & Outputs)  
**Primary Target**: Malaysian palm oil price (`palm_wb_myr`, RM/mt)  
**Secondary Target**: DOSM Producer Price Index SITC Section 4: Animal and vegetable oils and fats (`ppi_oilsfats_my`, 2010=100)  

---

## 1. Mandatory Statements & Scope

> [!IMPORTANT]
> 1. **Forecasting Demonstrator**: PalmGuard is a research and forecasting demonstrator. It is NOT trading, investment, hedging, or procurement advice.
> 2. **No Financial Benefit Measured**: No monetary savings, excess alpha, or financial return was evaluated or claimed.
> 3. **Empirical Intervals**: Conformal prediction coverage is strictly empirical based on observed historical errors and is NOT guaranteed for future distributions.
> 4. **Target Specification**: The primary palm oil series is derived from the World Bank Commodity Price Data ("Pink Sheet") converted to MYR/mt using Bank Negara Malaysia (BNM) trading-day monthly mean USD/MYR exchange rates. It reflects predominantly refined (RBD) Malaysian palm oil with documented delivery basis changes over time. **It is NOT the physical delivered Crude Palm Oil (CPO) price published by the Malaysian Palm Oil Board (MPOB)**.

---

## 2. Intended Use & Factors

- **Intended Use**: Operational benchmark forecasting for Malaysian agribusiness planners and macro analysts seeking monthly price forecasts 1, 2, and 3 months ahead with calibrated uncertainty bands.
- **Out of Scope**: Daily or intraday price forecasting, futures contract curve arbitrage, high-frequency trading execution, export quota optimization.
- **Relevant Factors**:
  - Global crude oil (Brent) and vegetable oil (Soybean oil) price shifts.
  - Ringgit to US Dollar exchange rate fluctuations.
  - Palm oil export trends and domestic producer price inertia.

---

## 3. Data Provenance & Ingestion

All data inputs are strictly open-access under **Creative Commons Attribution 4.0 International (CC BY 4.0)**:
1. **World Bank Commodity Price Data (Pink Sheet)**: 801 continuous monthly rows from 1960M01 to 2026M09.
2. **Bank Negara Malaysia (BNM)** via `data.gov.my`: 5,759 daily 17:00 middle USD/MYR rate records (2003–2026).
3. **Department of Statistics Malaysia (DOSM)**:
   - Producer Price Index (`ppi_sitc` Section 4): 200 continuous monthly rows (2010–2026).
   - Merchandise Trade (`trade_sitc_1d` Section 4 exports): 319 monthly rows (2000–2026).

All raw API pulls are stored in dated, immutable snapshots with SHA-256 manifests under `data/raw/`.

---

## 4. Modeling Strategy & Champion Selection Protocol

In accordance with `docs/05_FORECAST_EXPERIMENT_PLAN.md`:
- Candidate models evaluated:
  - **B1**: Naive (random walk last observed value)
  - **B2**: Seasonal Naive (12-month lag)
  - **B3**: Exponential Smoothing (ETS with damped trend)
  - **B4**: Autoregressive Integrated Moving Average (ARIMA)
  - **M1**: LightGBM with autoregressive return and calendar features
  - **M2**: LightGBM with exogenous macro drivers (Brent, Soyoil, USD/MYR, PPI, Exports)
- Selection Protocol:
  1. Lowest pooled validation MASE.
  2. If within a 2.0% relative MASE margin, the simpler model wins (B1 > B2 > B3 > B4 > M1 > M2).
  3. Selection record and artifacts frozen prior to holdout scoring.

### Selection Decisions (Checkpoint Gate G3):
- **`palm_wb_myr` Champion: B1 (Naive)**
  - Candidate B1 pooled validation MASE was 3.0992 vs best B4 (3.0606). The relative gap ($1.26\%$) fell within the $2.0\%$ tie-threshold, choosing the parsimonious baseline B1.
  - Interval method: **C2 (Adaptive Conformal Inference)**, mean validation coverage error 3.9 pp vs 5.3 pp for C1.
- **`ppi_oilsfats_my` Champion: B3 (ETS)**
  - Candidate B3 won outright with lowest pooled validation MASE of 1.1900 (WAPE 0.0205).
  - Interval method: **C2 (Adaptive Conformal Inference)**, mean validation coverage error 5.6 pp vs 9.4 pp for C1.

---

## 5. Measured Holdout Results (Checkpoint Gate G4)

Evaluated across **24 rolling holdout origins** (scored once behind an automated single-run lock):

| Series ID | Champion Model | Split | Horizon | n | MASE | WAPE | RMSE | MAE | Bias | Fit Failures |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `palm_wb_myr` | **B1** | Holdout | 1 | 23 | 1.1581 | 0.0394 | 249.53 | 176.54 | -7.62 | 0 |
| `palm_wb_myr` | **B1** | Holdout | 2 | 22 | 1.9093 | 0.0654 | 375.89 | 291.13 | 18.41 | 0 |
| `palm_wb_myr` | **B1** | Holdout | 3 | 21 | 2.3456 | 0.0811 | 426.97 | 357.70 | 51.81 | 0 |
| `palm_wb_myr` | **B1** | Holdout | Pooled | 66 | **1.7868** | **0.0612** | 356.09 | 272.38 | 19.97 | 0 |
| `ppi_oilsfats_my` | **B3** | Holdout | 1 | 23 | 0.8100 | 0.0123 | 2.07 | 1.61 | -0.21 | 0 |
| `ppi_oilsfats_my` | **B3** | Holdout | 2 | 22 | 1.8415 | 0.0278 | 4.29 | 3.66 | -0.41 | 0 |
| `ppi_oilsfats_my` | **B3** | Holdout | 3 | 21 | 2.8807 | 0.0434 | 6.74 | 5.72 | -0.66 | 0 |
| `ppi_oilsfats_my` | **B3** | Holdout | Pooled | 66 | **1.8133** | **0.0274** | 4.70 | 3.60 | -0.42 | 0 |

### Comparison Across All Candidates (Pooled Holdout MASE):
- **`palm_wb_myr`**: B4 (1.7649) | **B1 (1.7868)** | M2 (2.0555) | B3 (2.1152) | M1 (2.1685) | B2 (3.2987)
- **`ppi_oilsfats_my`**: M2 (1.4536) | B4 (1.6301) | M1 (1.6455) | **B3 (1.8133)** | B1 (1.8576) | B2 (5.0818)

---

## 6. Audit of Project Objectives

1. **Objective O1 (Data Continuity & Contracts)**: **PASSED**. 801 continuous monthly price rows and 200 PPI months ingested with zero missing values.
2. **Objective O2 (Hypothesis: Champion MASE $\le 0.95$ at $h=1$ on Validation)**:
   - `palm_wb_myr`: **MISSED** (Validation $h=1$ MASE was 2.0131).
   - `ppi_oilsfats_my`: **MET** (Validation $h=1$ MASE was 0.5515).
3. **Objective O3 (Validation Coverage within ±5 pp of Nominal)**: **MISSED** on both series. Interval method C2 (adaptive conformal) was selected on validation. Largest validation gap from nominal: `palm_wb_myr` 6.7 pp, `ppi_oilsfats_my` 9.6 pp, against a ±5 pp target. On the holdout, palm oil coverage was 77% to 83% at the 80% level; PPI bands were too narrow (59% to 70% at the 80% level). Full table: `reports/validation_coverage.csv`, `reports/holdout_coverage.csv`.
4. **Objective O4 (No Leakage)**: **PASSED**. Future mutation, DuckDB window static text, label cutoff, and publication lag tests passed with zero leaks.
5. **Objective O5 (Three Consecutive Scheduled Runs)**: **NOT YET MET**. The pipeline is idempotent locally and the cron workflows are written, but no scheduled run has executed because the repository has no GitHub remote.
6. **Objective O6 (Public API and Dashboard URLs)**: **NOT YET MET**. The API passes the smoke test on localhost only; nothing is deployed and the Docker image has not been built in CI.

---

## 7. Limitations & Caveats

- **Interval Calibration**: PPI bands under-covered on the holdout (59% to 82% against 80% and 90% nominal); treat them as indicative only.
- **Small Sample Uncertainty**: With 24 holdout observations, the binomial standard error of coverage at 80% nominal is $\approx 8.16$ percentage points.
- **Price Martingale Behavior**: Macro commodity spot prices closely approximate a martingale; complex ML regressors are prone to overfitting without proprietary daily orderbook signals.
- **Definition Breaks**: The World Bank Pink Sheet series incorporates delivery basis splices (most notably FOB Malaysia in 2021, and replacement FOB average export price in 2026).
