# Data Quality Report (Gate G1)

- **Generated (UTC)**: `2026-10-12T00:53:25+00:00`
- **Gate G1 Status**: **PASS**
- **Objective O1 (`palm_wb_myr >= 180` gap-free months & contracts pass)**: **PASS** (`277` months)
- **Selected Primary Target**: `palm_wb_myr` (Malaysian palm oil price (World Bank Pink Sheet, MYR/mt))
- **Selected Secondary Target**: `ppi_oilsfats_my` (DOSM Producer Price Index — SITC Section 4: Animal and vegetable oils and fats (2010=100))
- **Cross-check (`palm_wb_myr` vs `ppi_oilsfats_my` monthly log-return correlation)**: `0.5403` over `196` overlapping months
- **Logged Revisions (`data/processed/revisions.parquet`)**: `0` rows

## 1. Series Contract Summary

| Series ID | Snapshot ID | Rows | Start Month | End Month | Min | Max | Contiguous | Duplicates | Non-positive |
| --- | --- | ---: | --- | --- | ---: | ---: | --- | --- | --- |
| `palm_wb_usd` | `worldbank.pink_sheet.2026-10-11.ea1c35082787` | 801 | `1960-01-01` | `2026-09-01` | 142.00 | 1777.00 | Yes | No | No |
| `palm_wb_myr` | `worldbank.pink_sheet.2026-10-11.ea1c35082787+bnm.exchangerates_daily_1700.2026-10-12.fe359d6eed30` | 277 | `2003-05-01` | `2026-05-01` | 1592.20 | 7529.22 | Yes | No | No |
| `ppi_oilsfats_my` | `dosm.ppi_sitc.2026-10-11.482c1567e784` | 200 | `2010-01-01` | `2026-08-01` | 84.00 | 141.90 | Yes | No | No |
| `brent_wb_usd` | `worldbank.pink_sheet.2026-10-11.ea1c35082787` | 801 | `1960-01-01` | `2026-09-01` | 1.20 | 133.90 | Yes | No | No |
| `soyoil_wb_usd` | `worldbank.pink_sheet.2026-10-11.ea1c35082787` | 801 | `1960-01-01` | `2026-09-01` | 157.00 | 1963.00 | Yes | No | No |
| `usdmyr_avg` | `bnm.exchangerates_daily_1700.2026-10-12.fe359d6eed30` | 277 | `2003-05-01` | `2026-05-01` | 2.99 | 4.77 | Yes | No | No |
| `exports_sitc4` | `dosm.trade_sitc_1d.2026-10-11.6566da79934f` | 319 | `2000-01-01` | `2026-07-01` | 798687254.00 | 11093557354.00 | Yes | No | No |

## 2. World Bank Palm Oil Definition Breaks

The series is **not** adjusted across definition changes; breaks are recorded from the World Bank Pink Sheet `Description` sheet and displayed on the dashboard:

| Effective Date | World Bank Pink Sheet Basis Definition |
| --- | --- |
| `2001-12-01` | Palm oil (Malaysia), RBD, CIF Rotterdam (previously Malaysia 5%, CIF N.W. Europe, bulk) |
| `2021-01-01` | Palm oil (Malaysia), RBD, FOB Malaysia Ports |
| `2024-11-01` | Palm oil (Malaysia), 5% Bulk, CIF North West Europe |
| `2025-02-01` | Palm oil (Malaysia), Crude, DAP |
| `2026-01-01` | Palm oil (Malaysia), RBD, average export price FOB (October 2026 replacement series) |

## 3. Attribution & Disclaimer

- **Licence**: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
- **Transformation Note**: Values were transformed from source publications by computing monthly trading-day mean USD/MYR middle rates, converting USD/mt commodity prices to MYR/mt, and computing monthly log returns.
- **Disclaimer**: PalmGuard is a forecasting demonstrator. It is not trading, investment or procurement advice. No financial benefit was measured. Interval coverage is empirical on historical data and is not guaranteed.
