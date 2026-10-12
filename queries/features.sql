-- queries/features.sql
-- Computes lagged, rolling, and driver features from monthly_panel for a designated target series.
-- Enforces strictly backward-looking windows (ROWS BETWEEN ... AND CURRENT ROW / PRECEDING)
-- and publication lags (Pink Sheet & FX lag 1, PPI lag 2, Exports lag 3).
--
-- Input:
--   table: panel (from monthly_panel.sql)
-- Parameters:
--   $target_series: string ('palm_wb_myr' or 'ppi_oilsfats_my')
--
-- Output columns:
--   target_series_id: string
--   origin_month: string ('YYYY-MM-01')
--   y_origin: float (price/index at origin)
--
--   -- Target returns at horizon h=1, 2, 3: ln(y[t+h] / y[t])
--   -- Only populated if future target month is observed in the panel (otherwise NULL)
--   target_return_h1: float
--   target_return_h2: float
--   target_return_h3: float
--   y_target_h1: float
--   y_target_h2: float
--   y_target_h3: float
--
--   -- Own series log-return lags (r_t = ln(y[t] / y[t-1]))
--   return_lag1: float  -- r_t
--   return_lag2: float  -- r_{t-1}
--   return_lag3: float  -- r_{t-2}
--   return_lag6: float  -- r_{t-5}
--   return_lag12: float -- r_{t-11}
--
--   -- Rolling mean and std of returns (strictly backward-looking over completed origin months)
--   return_roll_mean_3m: float
--   return_roll_std_3m: float
--   return_roll_mean_6m: float
--   return_roll_std_6m: float
--   return_roll_mean_12m: float
--   return_roll_std_12m: float
--
--   -- Distance from 12-month high and low (level scale)
--   -- (y[t] - min_12m) / (max_12m - min_12m) and distance from max: (y[t] - max_12m) / max_12m
--   pct_dist_from_12m_max: float
--   pct_dist_from_12m_min: float
--
--   -- Calendar features
--   origin_month_num: integer (1..12)
--   origin_quarter: integer (1..4)
--
--   -- Exogenous drivers for M2 (aligned to origin t respecting publication lag)
--   -- Pink Sheet & FX (lag 1 -> at origin t, latest usable is t):
--   driver_usdmyr_return_1m: float
--   driver_usdmyr_roll_mean_3m: float
--   driver_brent_return_1m: float
--   driver_brent_roll_mean_3m: float
--   driver_soyoil_return_1m: float
--   driver_soyoil_roll_mean_3m: float
--
--   -- DOSM PPI (lag 2 -> at origin t, latest usable is t-1 month):
--   driver_ppi_return_1m: float
--   driver_ppi_roll_mean_3m: float
--
--   -- DOSM SITC-4 Exports (lag 3 -> at origin t, latest usable is t-2 months):
--   driver_exports_return_1m: float
--   driver_exports_roll_mean_3m: float

WITH target_panel AS (
    SELECT
        month,
        value AS y,
        ln(value / lag(value, 1) OVER (ORDER BY month)) AS ret_1m
    FROM panel
    WHERE series_id = $target_series
),
target_own_features AS (
    SELECT
        month AS origin_month,
        y AS y_origin,
        -- Forward lead targets (only for ground truth evaluation / training labels)
        lead(y, 1) OVER (ORDER BY month) AS y_target_h1,
        lead(y, 2) OVER (ORDER BY month) AS y_target_h2,
        lead(y, 3) OVER (ORDER BY month) AS y_target_h3,
        ln(lead(y, 1) OVER (ORDER BY month) / y) AS target_return_h1,
        ln(lead(y, 2) OVER (ORDER BY month) / y) AS target_return_h2,
        ln(lead(y, 3) OVER (ORDER BY month) / y) AS target_return_h3,

        -- Own return lags
        ret_1m AS return_lag1,
        lag(ret_1m, 1) OVER (ORDER BY month) AS return_lag2,
        lag(ret_1m, 2) OVER (ORDER BY month) AS return_lag3,
        lag(ret_1m, 5) OVER (ORDER BY month) AS return_lag6,
        lag(ret_1m, 11) OVER (ORDER BY month) AS return_lag12,

        -- Rolling mean and std of returns (3, 6, 12 months backward)
        avg(ret_1m) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS return_roll_mean_3m,
        stddev_samp(ret_1m) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS return_roll_std_3m,
        avg(ret_1m) OVER (ORDER BY month ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) AS return_roll_mean_6m,
        stddev_samp(ret_1m) OVER (ORDER BY month ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) AS return_roll_std_6m,
        avg(ret_1m) OVER (ORDER BY month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS return_roll_mean_12m,
        stddev_samp(ret_1m) OVER (ORDER BY month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS return_roll_std_12m,

        -- Distance from 12-month high and low (level scale)
        (y - max(y) OVER (ORDER BY month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW))
            / max(y) OVER (ORDER BY month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS pct_dist_from_12m_max,
        (y - min(y) OVER (ORDER BY month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW))
            / NULLIF(min(y) OVER (ORDER BY month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW), 0.0) AS pct_dist_from_12m_min,

        month(strptime(month, '%Y-%m-%d')) AS origin_month_num,
        quarter(strptime(month, '%Y-%m-%d')) AS origin_quarter
    FROM target_panel
),
usdmyr_raw AS (
    SELECT
        month,
        ln(value / lag(value, 1) OVER (ORDER BY month)) AS ret_1m
    FROM panel
    WHERE series_id = 'usdmyr_avg'
),
usdmyr_feat AS (
    -- Lag 1: at origin t, latest usable is t
    SELECT
        month AS origin_month,
        ret_1m AS driver_usdmyr_return_1m,
        avg(ret_1m) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS driver_usdmyr_roll_mean_3m
    FROM usdmyr_raw
),
brent_raw AS (
    SELECT
        month,
        ln(value / lag(value, 1) OVER (ORDER BY month)) AS ret_1m
    FROM panel
    WHERE series_id = 'brent_wb_usd'
),
brent_feat AS (
    -- Lag 1: at origin t, latest usable is t
    SELECT
        month AS origin_month,
        ret_1m AS driver_brent_return_1m,
        avg(ret_1m) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS driver_brent_roll_mean_3m
    FROM brent_raw
),
soyoil_raw AS (
    SELECT
        month,
        ln(value / lag(value, 1) OVER (ORDER BY month)) AS ret_1m
    FROM panel
    WHERE series_id = 'soyoil_wb_usd'
),
soyoil_feat AS (
    -- Lag 1: at origin t, latest usable is t
    SELECT
        month AS origin_month,
        ret_1m AS driver_soyoil_return_1m,
        avg(ret_1m) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS driver_soyoil_roll_mean_3m
    FROM soyoil_raw
),
ppi_raw AS (
    SELECT
        month,
        ln(value / lag(value, 1) OVER (ORDER BY month)) AS ret_1m
    FROM panel
    WHERE series_id = 'ppi_oilsfats_my'
),
ppi_feat AS (
    -- Lag 2: at origin t, latest usable is t-1
    SELECT
        strftime(strptime(month, '%Y-%m-%d') + INTERVAL 1 MONTH, '%Y-%m-01') AS origin_month,
        ret_1m AS driver_ppi_return_1m,
        avg(ret_1m) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS driver_ppi_roll_mean_3m
    FROM ppi_raw
),
exports_raw AS (
    SELECT
        month,
        ln(value / lag(value, 1) OVER (ORDER BY month)) AS ret_1m
    FROM panel
    WHERE series_id = 'exports_sitc4'
),
exports_feat AS (
    -- Lag 3: at origin t, latest usable is t-2
    SELECT
        strftime(strptime(month, '%Y-%m-%d') + INTERVAL 2 MONTH, '%Y-%m-01') AS origin_month,
        ret_1m AS driver_exports_return_1m,
        avg(ret_1m) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS driver_exports_roll_mean_3m
    FROM exports_raw
)
SELECT
    $target_series AS target_series_id,
    t.origin_month,
    t.y_origin,

    -- Labels
    t.y_target_h1,
    t.y_target_h2,
    t.y_target_h3,
    t.target_return_h1,
    t.target_return_h2,
    t.target_return_h3,

    -- Own features (M1)
    t.return_lag1,
    t.return_lag2,
    t.return_lag3,
    t.return_lag6,
    t.return_lag12,
    t.return_roll_mean_3m,
    t.return_roll_std_3m,
    t.return_roll_mean_6m,
    t.return_roll_std_6m,
    t.return_roll_mean_12m,
    t.return_roll_std_12m,
    t.pct_dist_from_12m_max,
    t.pct_dist_from_12m_min,
    t.origin_month_num,
    t.origin_quarter,

    -- Exogenous driver features (M2)
    u.driver_usdmyr_return_1m,
    u.driver_usdmyr_roll_mean_3m,
    b.driver_brent_return_1m,
    b.driver_brent_roll_mean_3m,
    s.driver_soyoil_return_1m,
    s.driver_soyoil_roll_mean_3m,
    p.driver_ppi_return_1m,
    p.driver_ppi_roll_mean_3m,
    e.driver_exports_return_1m,
    e.driver_exports_roll_mean_3m
FROM target_own_features t
LEFT JOIN usdmyr_feat u ON t.origin_month = u.origin_month
LEFT JOIN brent_feat b ON t.origin_month = b.origin_month
LEFT JOIN soyoil_feat s ON t.origin_month = s.origin_month
LEFT JOIN ppi_feat p ON t.origin_month = p.origin_month
LEFT JOIN exports_feat e ON t.origin_month = e.origin_month
ORDER BY t.origin_month;
