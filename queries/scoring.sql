-- queries/scoring.sql
-- Joins the forecast ledger with newly observed actuals from monthly_panel
-- Computes forecast errors (absolute, squared, percentage, scaled) and conformal
-- interval hits (80% and 90% coverage).
-- mase is the absolute error divided by the mean absolute one-step naive error of the
-- series up to the forecast origin (no rows after the origin are used).

WITH diffs AS (
    SELECT
        series_id,
        CAST(month AS VARCHAR) AS month,
        ABS(value - LAG(value) OVER (PARTITION BY series_id ORDER BY month)) AS abs_diff
    FROM monthly_panel
),
scales AS (
    SELECT
        series_id,
        month,
        AVG(abs_diff) OVER (
            PARTITION BY series_id ORDER BY month
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS naive_scale
    FROM diffs
)
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
    ABS(act.value - fl.y_pred) / NULLIF(sc.naive_scale, 0) AS mase,
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
LEFT JOIN scales sc
    ON fl.series_id = sc.series_id
    AND fl.origin_month = sc.month
ORDER BY fl.series_id, fl.target_month, fl.horizon;
