-- queries/calendar.sql
-- Generates calendar dimension rows for a monthly origin and horizon pair.
-- Output columns:
--   origin_month: date string 'YYYY-MM-01'
--   horizon: integer 1..3
--   target_month: date string 'YYYY-MM-01'
--   origin_month_num: integer 1..12 (1-indexed month of origin)
--   target_month_num: integer 1..12 (1-indexed month of target)
--   origin_quarter: integer 1..4
--   target_quarter: integer 1..4

SELECT
    strftime(origin_dt, '%Y-%m-01') AS origin_month,
    h AS horizon,
    strftime(origin_dt + INTERVAL (h) MONTH, '%Y-%m-01') AS target_month,
    month(origin_dt) AS origin_month_num,
    month(origin_dt + INTERVAL (h) MONTH) AS target_month_num,
    quarter(origin_dt) AS origin_quarter,
    quarter(origin_dt + INTERVAL (h) MONTH) AS target_quarter
FROM (
    SELECT
        strptime(origin_month_str, '%Y-%m-%d') AS origin_dt,
        CAST(h AS INTEGER) AS h
    FROM calendar_origins
    CROSS JOIN (VALUES (1), (2), (3)) AS horizons(h)
);
