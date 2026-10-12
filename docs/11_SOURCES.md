# 11. Sources

All entries checked on 2026-10-11 unless noted.

## 1. Data sources in use (all CC BY 4.0)

| Source | URL | Confirmed |
| --- | --- | --- |
| World Bank commodity markets (Pink Sheet) | https://www.worldbank.org/en/research/commodity-markets | Monthly xlsx (`CMO-Historical-Data-Monthly.xlsx`, updated 2 Oct 2026); `Palm oil` (`$/mt`), `Crude oil, Brent` (`$/bbl`), `Soybean oil` (`$/mt`), 801 rows (`1960M01`–`2026M09`); definition by period confirmed in T03 |
| World Bank dataset licences | https://datacatalog.worldbank.org/public-licenses | CC BY 4.0 default for World Bank datasets |
| data.gov.my API documentation | https://developer.data.gov.my/request-query | Static APIs: `filter=<val>@<col>`, `date_start=<YYYY-MM-DD>@<col>`, `date_end=<YYYY-MM-DD>@<col>`, `sort=<col>`, `limit=<int>` confirmed in T04 |
| data.gov.my rate limit | https://developer.data.gov.my/rate-limit | 4 requests per minute; HTTP 429 beyond |
| data.gov.my data catalogue endpoint | https://developer.data.gov.my/static-api/data-catalogue | `GET https://api.data.gov.my/data-catalogue/?id=<id>` |
| Daily exchange rates at 1700 (BNM) | https://data.gov.my/data-catalogue/exchangerates_daily_1700 | Daily since 2003 (5,759 middle-rate rows, `2003-05-02` to `2026-10-09`) |
| Monthly PPI by SITC section (DOSM) | https://data.gov.my/data-catalogue/ppi_sitc | Base 2010 = 100; section 4 has 200 months (`2010-01` to `2026-08`); latest 3 months revisable |
| Monthly trade by SITC section (DOSM) | https://data.gov.my/data-catalogue/trade_sitc_1d | 319 section-4 monthly rows (`2000-01` to `2026-07`); latest two months provisional |
| SITC lookup | https://api.data.gov.my/data-catalogue/?id=sitc | Section 4 = "Animal and vegetable oils, and fats" (9 rows) |

## 2. Checked and not used

| Source | URL | Reason |
| --- | --- | --- |
| MPOB price PDFs | https://price.mpob.gov.my/pdf/monthly/cpo/2022-12-01 | Publicly fetchable, but © MPOB all rights reserved; would need permission |
| MPOB statistics portal | https://bepi.mpob.gov.my/ | Login required; data subscriptions sold |
| data.gov.my catalogue listing | https://data.gov.my/data-catalogue | No palm oil price dataset |
| Archived annual CPO by region | https://archive.data.gov.my/data/dataset/annual-price-of-crude-palm-oil-cpo-by-region-malaysia | Ends 2016 |
| FRED global palm oil price (IMF) | https://fred.stlouisfed.org/series/PPOILUSDM | Copyrighted; last updated Aug 2026 |
| Fuel prices | https://data.gov.my/data-catalogue/fuelprice | Government-administered prices |

## 3. Still to verify during implementation

- Render and Streamlit Community Cloud free-tier terms (T23).
- Current MAPIE time-series API (T13).

## 4. Internal reference

Structure and conventions follow `../../03_DemandGuard_Demand_Forecasting_Inventory_Optimisation` (pyproject, CI workflow, Dockerfile, config, task format).
