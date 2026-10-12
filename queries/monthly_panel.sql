-- queries/monthly_panel.sql
-- Canonical monthly panel construction in DuckDB as of a specified vintage date ($as_of).
-- Excludes any snapshot with available_from > $as_of.
-- Computes monthly mean USD/MYR exchange rate across trading days in completed months,
-- and converts palm_wb_usd into palm_wb_myr.

WITH raw_snapshots_filtered AS (
    SELECT
        source,
        dataset,
        snapshot_id,
        available_from,
        row_number() OVER (
            PARTITION BY source, dataset
            ORDER BY available_from DESC, snapshot_id DESC
        ) AS snap_rank
    FROM raw_manifests
    WHERE strptime(available_from, '%Y-%m-%d') <= strptime($as_of, '%Y-%m-%d')
),
latest_manifests AS (
    SELECT source, dataset, snapshot_id, available_from
    FROM raw_snapshots_filtered
    WHERE snap_rank = 1
),
daily_fx AS (
    SELECT
        d.date,
        strftime(strptime(d.date, '%Y-%m-%d'), '%Y-%m-01') AS month,
        CAST(d.USD AS DOUBLE) AS usd_rate,
        m.snapshot_id,
        m.available_from
    FROM raw_exchangerates d
    JOIN latest_manifests m
      ON m.source = 'bnm' AND m.dataset = 'exchangerates_daily_1700'
    WHERE lower(d.rate_type) = 'middle'
      AND strptime(d.date, '%Y-%m-%d') <= strptime($as_of, '%Y-%m-%d')
),
fx_month_bounds AS (
    SELECT
        month,
        max(day(strptime(date, '%Y-%m-%d'))) AS max_day_in_month,
        avg(usd_rate) AS usdmyr_avg,
        max(snapshot_id) AS snapshot_id,
        max(available_from) AS available_from
    FROM daily_fx
    GROUP BY month
),
complete_fx_monthly AS (
    -- Completed calendar month filter: only months that concluded by the 25th
    SELECT
        'usdmyr_avg' AS series_id,
        month,
        usdmyr_avg AS value,
        available_from,
        snapshot_id,
        false AS is_provisional
    FROM fx_month_bounds
    WHERE max_day_in_month >= 25
),
pink_sheet_series AS (
    SELECT
        p.series_id,
        p.month,
        CAST(p.value AS DOUBLE) AS value,
        m.available_from,
        m.snapshot_id,
        false AS is_provisional
    FROM raw_pink_sheet p
    JOIN latest_manifests m
      ON m.source = 'worldbank' AND m.dataset = 'pink_sheet'
    WHERE strptime(p.month, '%Y-%m-%d') <= strptime($as_of, '%Y-%m-%d')
      AND p.series_id IN ('palm_wb_usd', 'brent_wb_usd', 'soyoil_wb_usd')
),
palm_myr_converted AS (
    SELECT
        'palm_wb_myr' AS series_id,
        p.month,
        p.value * fx.value AS value,
        CASE
            WHEN strptime(p.available_from, '%Y-%m-%d') >= strptime(fx.available_from, '%Y-%m-%d')
            THEN p.available_from
            ELSE fx.available_from
        END AS available_from,
        p.snapshot_id || '+' || fx.snapshot_id AS snapshot_id,
        false AS is_provisional
    FROM pink_sheet_series p
    JOIN complete_fx_monthly fx ON p.month = fx.month
    WHERE p.series_id = 'palm_wb_usd'
),
ppi_series AS (
    SELECT
        'ppi_oilsfats_my' AS series_id,
        strftime(strptime(p.date, '%Y-%m-%d'), '%Y-%m-01') AS month,
        CAST(p.index AS DOUBLE) AS value,
        m.available_from,
        m.snapshot_id,
        -- The latest 3 months published by DOSM are provisional
        row_number() OVER (ORDER BY strptime(p.date, '%Y-%m-%d') DESC) <= 3 AS is_provisional
    FROM raw_ppi p
    JOIN latest_manifests m
      ON m.source = 'dosm' AND m.dataset = 'ppi_sitc'
    WHERE lower(p.series) = 'abs'
      AND CAST(p.section AS VARCHAR) = '4'
      AND strptime(p.date, '%Y-%m-%d') <= strptime($as_of, '%Y-%m-%d')
),
trade_series AS (
    SELECT
        'exports_sitc4' AS series_id,
        strftime(strptime(t.date, '%Y-%m-%d'), '%Y-%m-01') AS month,
        CAST(t.exports AS DOUBLE) AS value,
        m.available_from,
        m.snapshot_id,
        -- The latest 2 months published by DOSM are provisional
        row_number() OVER (ORDER BY strptime(t.date, '%Y-%m-%d') DESC) <= 2 AS is_provisional
    FROM raw_trade t
    JOIN latest_manifests m
      ON m.source = 'dosm' AND m.dataset = 'trade_sitc_1d'
    WHERE CAST(t.section AS VARCHAR) = '4'
      AND strptime(t.date, '%Y-%m-%d') <= strptime($as_of, '%Y-%m-%d')
),
combined AS (
    SELECT * FROM pink_sheet_series
    UNION ALL
    SELECT * FROM complete_fx_monthly
    UNION ALL
    SELECT * FROM palm_myr_converted
    UNION ALL
    SELECT * FROM ppi_series
    UNION ALL
    SELECT * FROM trade_series
)
SELECT
    series_id,
    month,
    value,
    available_from,
    snapshot_id,
    is_provisional
FROM combined
WHERE value IS NOT NULL AND value > 0.0
ORDER BY series_id, month;
