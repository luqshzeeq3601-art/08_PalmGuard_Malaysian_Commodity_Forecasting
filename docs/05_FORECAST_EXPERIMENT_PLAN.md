# 05. Forecast experiment plan

Status: DRAFT, 2026-10-11. Everything here is fixed before any model is fitted.

## 1. Question

Can a lag-based LightGBM forecast the monthly palm oil price in MYR (World Bank benchmark) 1 to 3 months ahead better than naive, seasonal naive, ETS and ARIMA under a fixed rolling-origin protocol, and do conformal intervals reach their nominal coverage?

The same protocol is run on the second series, DOSM PPI section 4 (oils and fats), with the shorter split in section 4. Each series has its own selection record and holdout. Results are reported separately and never pooled.

Prior expectation: commodity prices are close to a random walk, so the naive forecast is hard to beat. The plan treats "naive wins" as a normal result.

## 2. Candidates

| ID | Forecast | Definition |
| --- | --- | --- |
| B1 | Naive | `y[t+h] = y[t]` |
| B2 | Seasonal naive | `y[t+h] = y[t+h-12]` |
| B3 | ETS | statsmodels ETS on log price, additive error and damped trend, no seasonality; refit each origin |
| B4 | ARIMA | Log price, orders (0,1,1) and (1,1,0); order chosen on validation; refit each origin |
| M1 | LightGBM, lags only | Direct model per horizon on own-series features |
| M2 | LightGBM, lags plus drivers | M1 features plus exogenous drivers allowed by the lag table |

ETS and ARIMA fit failures are logged per origin and replaced by B1 for that origin; the combined policy is what is scored.

## 3. Features and target (M1, M2)

Target: `ln(y[t+h] / y[t])`. Forecast price is `y[t] * exp(prediction)`.

- Own series: log-return lags 1, 2, 3, 6, 12; rolling mean and standard deviation of returns over 3, 6, 12 months; distance from 12-month high and low.
- Calendar: month of origin, month of target, horizon.
- M2 only, for the palm oil target: one-month return and 3-month rolling mean of USD/MYR, Brent, soybean oil (lag 1), of PPI section 4 (lag 2), and of SITC-4 exports (lag 3).
- M2 only, for the PPI series: the same drivers shifted so that none is later than the PPI origin month (and respecting each driver's publication lag).

Not allowed: any value from the target month or later, centred windows, full-sample scaling, drivers whose publication timing is unconfirmed. Trees need no scaling, so no fitted preprocessing exists to leak.

## 4. Protocol

1. Rolling origin with an expanding training window, monthly origins. No random splits.
2. Palm oil target: minimum 120 training months, 60 validation origins, final 24 holdout origins.
3. PPI series (200 months): minimum 96 training months, 48 validation origins, final 24 holdout origins. All frozen in `split_manifest.json`.
4. At each origin every candidate is fitted on data available at that origin and forecasts h = 1, 2, 3.
5. All candidates are scored on the same origin and horizon rows.
6. Data vintage: backtests use the frozen modelling vintage. True historical vintages do not exist before the first snapshot; this limitation is stated in the model card. Live forecasts use the vintage at the origin.

## 5. Bounded tuning

- Seed 42, CPU.
- LightGBM grid declared in config before running, at most 8 configurations over `num_leaves` {4, 8}, `min_child_samples` {5, 10}, `learning_rate` {0.03, 0.08}, with a fixed estimator count of 200. No early stopping on scored folds.
- Squared-error objective.
- The grid is not expanded after results are seen.

## 6. Prediction intervals

Nominal levels 80% and 90%, per horizon, built on the champion and reported for B1 as reference.

| Method | Definition |
| --- | --- |
| C1 Rolling split conformal | At origin `t`, half-width is the empirical quantile of absolute out-of-sample residuals (log-return scale) from earlier origins, trailing window of 60 |
| C2 Adaptive conformal inference | Same residual scores, but the working miscoverage level is updated online: `alpha[t+1] = alpha[t] + gamma * (alpha_target - miss[t])`, gamma fixed in config |
| C3 MAPIE time-series method | Spike in T13. Kept as a comparator only if the current API fits one module |

Residuals used at origin `t` come only from forecasts whose targets were observed by `t`. A horizon-`h` residual becomes available `h` months after its origin.

Choice between C1 and C2 is made on validation by coverage error first, mean width second. Coverage is reported as measured, with a binomial interval. No guarantee is claimed: the exchangeability assumption behind conformal coverage does not hold for a price series.

## 7. Metrics

All reported per horizon and pooled.

| Metric | Definition |
| --- | --- |
| MASE | Mean absolute error divided by the in-sample mean absolute one-step naive error of the training window. Primary |
| WAPE | `sum(abs(y - yhat)) / sum(y)`, also as a ratio to B1's WAPE |
| Pinball loss | At quantiles 0.05, 0.10, 0.50, 0.90, 0.95, using interval bounds as quantiles |
| Coverage | Share of actuals inside the interval, against nominal 80% and 90%, with a binomial interval |
| Mean interval width | RM/tonne (index points for the PPI series) and as a percentage of the level |
| Bias | Mean signed error |

For B1 at h = 1 on the scaling window MASE is close to 1 by construction.

## 8. Selection

1. Lowest pooled validation MASE wins.
2. If within 2% relative MASE, the simpler candidate wins. Order: B1, B2, B3, B4, M1, M2.
3. `artifacts/champion/selection_record.json` is written with a timestamp before the holdout is scored.

## 9. Success targets

From 01_PROBLEM_AND_OBJECTIVES.md, repeated for the record:

- O2: champion MASE ≤ 0.95 at h = 1 on validation (hypothesis).
- O3: validation coverage within ±5 points of nominal at each horizon for both levels.

A missed target is reported as missed.

## 10. Final holdout

1. Freeze champion, features, grid choice, interval method and settings.
2. Run the 24 holdout origins once with the same expanding-window refit rule.
3. Report all metrics for every candidate. Do not choose a new champion or retune from these results.
4. A guard file records that the holdout was scored; the `holdout` command refuses a second run without an explicit override that labels the output exploratory.

Evidence is limited: about 24 points per horizon. At 80% nominal the standard error of coverage is about 8 points. The report says so.

## 11. Required outputs

- `reports/validation_metrics.csv`, `reports/holdout_metrics.csv`: model, split, horizon, metrics, fit failures.
- `reports/predictions.parquet`: model, origin, target, horizon, actual, prediction, bounds, split.
- `reports/forecast_comparison.md`: selection reason, targets met or missed, limitations.
- `artifacts/champion/`: bundle from 04_TECHNICAL_DESIGN.md section 5.
- `docs/MODEL_CARD.md`: written at release from measured results only.

## 12. Statements required in every report

- Forecasting demonstrator; not trading or investment advice.
- No financial benefit was measured.
- Coverage is empirical, not guaranteed.
- The target is the World Bank palm oil benchmark in MYR, not the MPOB CPO price; any definition break inside the sample is named with its date.
