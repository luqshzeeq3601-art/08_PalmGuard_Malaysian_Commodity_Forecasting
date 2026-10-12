# 03. Data specification

Status: DRAFT, revised 2026-10-11 (decision: open-licence sources only; MPOB removed). Source facts were checked on 2026-10-11 unless marked UNVERIFIED.

## 1. Source decision

data.gov.my and OpenDOSM publish no CPO price series. MPOB publishes CPO prices, but under reserved copyright and partly behind a login. To avoid any permission requirement, PalmGuard uses only CC BY 4.0 sources:

- **Target**: World Bank Pink Sheet palm oil price, converted from USD to MYR with BNM exchange rates.
- **Second series**: DOSM Producer Price Index for SITC section 4, "Animal and vegetable oils, and fats", pulled through the data.gov.my API and run through the same pipeline.

| ID | Source and URL | Content | Frequency | Access | Licence | Role |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | World Bank Pink Sheet, landing `https://www.worldbank.org/en/research/commodity-markets`, file `CMO-Historical-Data-Monthly.xlsx` (resolved URL `https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx`) | Sheet `Monthly Prices` (updated 2 Oct 2026, 801 rows, `1960M01`–`2026M09`, no gaps): `Palm oil` (`$/mt`, col 22), `Crude oil, Brent` (`$/bbl`, col 2), `Soybean oil` (`$/mt`, col 25) | Monthly, early each month (next update 3 Nov 2026) | xlsx; URL includes a per-release hash, resolved from the landing page | CC BY 4.0 (`https://datacatalog.worldbank.org/public-licenses`) | Target (palm oil), drivers |
| S2 | data.gov.my API, `https://api.data.gov.my/data-catalogue/?id=<id>`; docs `https://developer.data.gov.my/request-query` | REST JSON; confirmed parameters: `filter=<val>@<col>`, `date_start=<YYYY-MM-DD>@<col>`, `date_end=<YYYY-MM-DD>@<col>`, `sort=<col>`, `limit=<int>` | Per dataset | No key; 4 requests/minute; HTTP 429 beyond | CC BY 4.0 | API ingestion |
| S3 | `exchangerates_daily_1700`, `https://data.gov.my/data-catalogue/exchangerates_daily_1700`; bulk `https://storage.data.gov.my/finsector/exr/daily_1700.parquet` | BNM daily rates since 2003 (5,759 middle-rate rows, `2003-05-02` to `2026-10-09`); `date`, `rate_type` (buying/selling/middle), 27 currency columns; MYR per unit | Daily (trading days) | API and parquet | CC BY 4.0 | Currency conversion, driver |
| S4 | `ppi_sitc`, `https://data.gov.my/data-catalogue/ppi_sitc`; bulk `https://storage.dosm.gov.my/ppi/ppi_sitc.csv` | DOSM PPI by SITC section, base 2010 = 100; `series` (abs, growth_yoy, growth_mom), `date`, `section`, `index`. Section 4: 200 months, `2010-01` to `2026-08`. Latest 3 months may be revised | Monthly, about the 28th for the previous month | API, CSV, parquet | CC BY 4.0 | Second series, driver |
| S5 | `trade_sitc_1d`, `https://data.gov.my/data-catalogue/trade_sitc_1d`; bulk `https://storage.dosm.gov.my/trade/trade_sitc_1d.parquet` | DOSM `date`, `section` (0-9, overall), `exports`, `imports` in RM (319 section-4 rows, `2000-01` to `2026-07`); latest two months provisional | Monthly (data.gov.my feed lags 2 months behind Pink Sheet) | API and parquet | CC BY 4.0 | Driver (section 4 exports) |
| S6 | `sitc` lookup via S2 | Section 4 = "Animal and vegetable oils, and fats" (9 rows) | Static | API | CC BY 4.0 | Definition |

What the target is and is not (verified in T03 from sheet `Description`):

- **Exact World Bank `Palm oil` definition by period**:
  - **Jan 2026 – present**: Palm oil (Malaysia), RBD, average export price FOB *(note in file: "October 2026: Replacement series for Palm oil from January 2026")*.
  - **Feb 2025 – Dec 2025**: Palm oil (Malaysia), Crude, DAP.
  - **Nov 2024 – Jan 2025**: Palm oil (Malaysia), 5% Bulk, CIF North West Europe.
  - **Jan 2021 – Oct 2024**: Palm oil (Malaysia), RBD, FOB Malaysia Ports.
  - **Dec 2001 – Dec 2020**: Palm oil (Malaysia), RBD, CIF Rotterdam.
  - **Before Dec 2001**: Malaysia 5%, c.i.f. N.W. Europe, bulk, nearest forward.
  - **Underlying sources cited by World Bank**: S&P Global (formerly Markit Group Limited / IHS Markit Agribusiness UK Ltd), Bloomberg Finance L.P., ISTA Mielke GmbH (Oil World), US Department of Agriculture, World Bank.
- **Driver definitions from `Description` sheet**:
  - `Crude oil, Brent` (`$/bbl`): *"Crude oil, UK Brent 38` API."*
  - `Soybean oil` (`$/mt`): *"Soybean oil, from January 2025, U.S. Soybean Oil, Crude Degummed, FOB U.S. Gulf; January 2021-December 2024, Dutch Soyoil Crude Degummed, EXW Dutch Mills; January 1999 to December 2020, Dutch crude degummed, FOB NW Europe; previously crude, f.o.b. ex-mill Netherlands, nearest forward."*
- It is predominantly refined (RBD) Malaysian palm oil, with brief crude/CIF splices in Nov 2024–Dec 2025. It is **not** the MPOB local delivered CPO price. All documents and the dashboard must describe it by this verified World Bank definition, never as "MPOB CPO price".
- The PPI section 4 index covers all animal and vegetable oils and fats produced in Malaysia. Palm products dominate that section, but the index is not a CPO price.

Checked and not used:

- MPOB price PDFs `https://price.mpob.gov.my/` and portal `https://bepi.mpob.gov.my/`: copyright reserved, data sold, portal behind login.
- `archive.data.gov.my` annual CPO by region: ends 2016.
- FRED `PPOILUSDM` (IMF): copyrighted, updated late.
- `fuelprice`: government-administered prices.

Verified in T03, T04 and T05: Pink Sheet palm oil, Brent and soybean oil columns, start date (`1960-01-01`) and definition changes (T03); data.gov.my date filter syntax (`date_start=<YYYY-MM-DD>@<col>`, `filter=<val>@<col>`) and all 4 datasets ingested (T04); publication timing and lag table confirmed/corrected (T05).

## 2. Licence handling

All sources are CC BY 4.0. Requirements: credit the World Bank, Bank Negara Malaysia and the Department of Statistics Malaysia; link the licence; state that values were transformed (currency conversion, monthly averaging, log returns). Raw snapshots may be committed to the public repository. No permission request is needed.

## 3. Raw snapshot contract

Path: `data/raw/<source>/<dataset>/retrieved=<YYYY-MM-DD>/<file>` plus `manifest.json` beside it.

| Manifest field | Meaning |
| --- | --- |
| `source`, `dataset` | Identifiers from this document |
| `request_url`, `resolved_url`, `http_status` | What was asked and what answered |
| `retrieved_at_utc` | ISO timestamp |
| `sha256`, `bytes` | Content hash and size |
| `schema_version`, `row_count` | Contract version and parsed rows |
| `snapshot_id` | `<source>.<dataset>.<date>.<sha256[:12]>` |

Rules:

1. Immutable. An existing snapshot path is never opened for writing.
2. Idempotent. If the new content hash equals the latest snapshot's hash, write nothing and log "no change".
3. Validated first. Content failing its contract is not stored as a snapshot; the run stops with the reason.
4. Vintage. Every processed table, model artifact and forecast row records the snapshot IDs it was built from.
5. Revisions. `data/processed/revisions.parquet` records series, period, old value, new value and both snapshot IDs. DOSM states that recent PPI and trade months are revised, so this log is expected to fill.

## 4. Canonical schemas

`monthly_panel` (one row per series, month, vintage):

| Field | Type | Rule |
| --- | --- | --- |
| `series_id` | string | `palm_wb_usd`, `palm_wb_myr`, `ppi_oilsfats_my`, `brent_wb_usd`, `soyoil_wb_usd`, `usdmyr_avg`, `exports_sitc4` |
| `month` | date | First day of month; continuous, no duplicates |
| `value` | double | Finite; prices and indices strictly positive |
| `available_from` | date | First date the value was published or retrieved |
| `snapshot_id` | string | Source snapshot |
| `is_provisional` | boolean | True for months DOSM marks as revisable |

Target construction: `palm_wb_myr[m] = palm_wb_usd[m] * usdmyr_avg[m]`, where `usdmyr_avg` is the mean of BNM daily middle rates at 1700 over trading days in month `m`. Computed in SQL. The MYR series starts in 2003 with the BNM data.

## 5. Publication lags

The full pipeline runs on the 8th of month `m+1`. The latest complete month is `m`. Empirical check on `2026-10-11` (after the 8th of October 2026, where `m = 2026-09`):

- **World Bank Pink Sheet (`S1`)**: Published on the 2nd–5th business day of `m+1` (October 2026 file updated `2026-10-02` with `2026-09` actuals; next update scheduled `2026-11-03`).
- **BNM Exchange Rates (`S3`)**: Published daily at 17:00 MYT on trading days; month `m` is complete by the 1st of `m+1`.
- **DOSM PPI SITC (`S4`)**: Published around the 28th of `m+1` for month `m`; on the 8th of `m+1`, the latest published month is `m-1` (`2026-08` on `2026-10-11`).
- **DOSM Trade SITC (`S5`)**: Although DOSM's headline trade release occurs late in `m+1`, the `trade_sitc_1d` catalogue dataset on `data.gov.my` lags an extra month (`2026-07` = `m-2` was the latest month present on `2026-10-11`). Declared lag is therefore corrected from 2 to **3 months** (`m-2`).

| Series | `series_id` | Declared lag (months) | Latest month usable at origin `m` |
| --- | --- | --- | --- |
| Palm oil, Brent, soybean oil (Pink Sheet) | `palm_wb_usd`, `brent_wb_usd`, `soyoil_wb_usd`, `palm_wb_myr` | 1 | `m` |
| USD/MYR monthly mean | `usdmyr_avg` | 1 | `m` |
| PPI section 4 | `ppi_oilsfats_my` | 2 | `m-1` |
| SITC-4 exports | `exports_sitc4` | 3 | `m-2`, provisional value from the snapshot available at the origin |

The PPI series, when forecast as its own target, uses its latest published month as origin (and aligns drivers so none is later than that origin minus each driver's relative lag). Lags live in `config/project.yaml` and are enforced in SQL and by a static test. A driver whose real availability cannot be confirmed is dropped, not guessed.

## 6. Data quality gate G1

- Target: at least 180 consecutive monthly observations of `palm_wb_myr` (O1). Expected about 285.
- No duplicate months, no nonpositive values, no gaps.
- Definition breaks in the palm oil series are listed with dates from the file's notes. A break inside the sample is reported and shown on the dashboard; the series is not adjusted.
- Cross-check: `palm_wb_myr` against `ppi_oilsfats_my` (correlation of monthly returns) reported for plausibility.
- Fallback: if the Pink Sheet has no usable palm oil column, `ppi_oilsfats_my` becomes the target with the shorter split in section 7. The decision is logged before modelling.

Outputs: `reports/data_quality.md`, `reports/data_quality_audit.json`.

## 7. Split contract

Number complete target months `1..N` at the frozen modelling vintage.

| Series | Minimum training months | Validation origins | Holdout origins |
| --- | --- | --- | --- |
| `palm_wb_myr` (target) | 120 | 60 | final 24 |
| `ppi_oilsfats_my` (second series, 200 months) | 96 | 48 | final 24 |

- Each origin forecasts h = 1, 2, 3 where the target month exists.
- `data/processed/split_manifest.json` records origins, target months, modelling vintage and hashes per series. It is written before any model is fitted.
- No validation target month may fall inside the holdout target range.
- Live origins after the frozen vintage are scored separately and labelled "live".
