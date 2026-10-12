-- queries/scoring.sql
-- Joins the forecast ledger with newly observed actuals from monthly_panel
-- Computes forecast errors (MAE, RMSE, MASE, WAPE, absolute percentage error, bias)
-- and conformal interval hits (80% and 90% coverage).

SELECT
    fl.series_id,
    fl.model_id,
    fl.origin_month,
    fl.target_month,
    fl.horizon,
    fl.model_version,
    fl.y_pred,
    fl.q80_lower,
    fl.q80_upper,
    fl.q90_lower,
    fl.q90_upper,
    act.value AS y_actual,
    (act.value - fl.y_pred) AS error,
    ABS(act.value - fl.y_pred) AS abs_error,
    POW(act.value - fl.y_pred, 2) AS sq_error,
    ABS(act.value - fl.y_pred) / act.value AS abs_pct_error,
    CASE
        WHEN act.value >= fl.q80_lower AND act.value <= fl.q80_upper THEN 1
        ELSE 0
    END AS interval_hit_80,
    CASE
        WHEN act.value >= fl.q90_lower AND act.value <= fl.q90_upper THEN 1
        ELSE 0
    END AS interval_hit_90,
    fl.forecast_timestamp_utc
FROM forecast_ledger fl
INNER JOIN monthly_panel act
    ON fl.series_id = act.series_id
    AND fl.target_month = CAST(act.month AS VARCHAR)
ORDER BY fl.series_id, fl.target_month, fl.horizon;
