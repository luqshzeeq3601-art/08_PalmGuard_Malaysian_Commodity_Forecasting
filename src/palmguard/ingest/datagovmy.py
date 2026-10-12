"""data.gov.my and OpenDOSM bulk backfill and incremental API ingestor."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import httpx
import pandas as pd

from palmguard.http import fetch_url
from palmguard.ingest.snapshots import (
    SnapshotManifest,
    SnapshotValidationError,
    SnapshotWriteResult,
    latest_snapshot,
    write_snapshot,
)

DATAGOVMY_API_URL = "https://api.data.gov.my/data-catalogue/"

EXCHANGERATES_BULK_URL = "https://storage.data.gov.my/finsector/exr/daily_1700.parquet"
PPI_SITC_BULK_URL = "https://storage.dosm.gov.my/ppi/ppi_sitc.csv"
TRADE_SITC_BULK_URL = "https://storage.dosm.gov.my/trade/trade_sitc_1d.parquet"


@dataclass(frozen=True)
class DatasetSpec:
    """Specification for a data.gov.my dataset."""

    source: str
    dataset: str
    bulk_url: str | None
    bulk_filename: str
    default_filters: dict[str, str]
    date_column: str | None


DATASET_SPECS: dict[str, DatasetSpec] = {
    "exchangerates_daily_1700": DatasetSpec(
        source="bnm",
        dataset="exchangerates_daily_1700",
        bulk_url=EXCHANGERATES_BULK_URL,
        bulk_filename="daily_1700.parquet",
        default_filters={"rate_type": "middle"},
        date_column="date",
    ),
    "ppi_sitc": DatasetSpec(
        source="dosm",
        dataset="ppi_sitc",
        bulk_url=PPI_SITC_BULK_URL,
        bulk_filename="ppi_sitc.csv",
        default_filters={"series": "abs", "section": "4"},
        date_column="date",
    ),
    "trade_sitc_1d": DatasetSpec(
        source="dosm",
        dataset="trade_sitc_1d",
        bulk_url=TRADE_SITC_BULK_URL,
        bulk_filename="trade_sitc_1d.parquet",
        default_filters={"section": "4"},
        date_column="date",
    ),
    "sitc": DatasetSpec(
        source="dosm",
        dataset="sitc",
        bulk_url=None,
        bulk_filename="sitc.json",
        default_filters={},
        date_column=None,
    ),
}


def build_catalogue_params(
    dataset_id: str,
    *,
    filters: Mapping[str, str] | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    date_column: str = "date",
    sort: str | None = None,
    limit: int | None = None,
) -> dict[str, str]:
    """Build query parameters matching the official developer.data.gov.my request-query syntax.

    Confirmed syntax (`https://developer.data.gov.my/request-query`):
    - `filter=<value_1>@<column_1>,<value_2>@<column_2>`
    - `date_start=<YYYY-MM-DD>@<date_column>`
    - `date_end=<YYYY-MM-DD>@<date_column>`
    - `sort=<column>` or `sort=-<column>`
    - `limit=<integer>`
    """
    params: dict[str, str] = {"id": dataset_id}
    if filters:
        params["filter"] = ",".join(f"{val}@{col}" for col, val in filters.items())
    if date_start:
        params["date_start"] = f"{date_start}@{date_column}"
    if date_end:
        params["date_end"] = f"{date_end}@{date_column}"
    if sort:
        params["sort"] = sort
    if limit is not None:
        params["limit"] = str(int(limit))
    return params


def _extract_json_records(payload: bytes) -> list[dict[str, object]]:
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise SnapshotValidationError(f"Invalid JSON response from data.gov.my: {exc}") from exc

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
        return parsed["data"]
    raise SnapshotValidationError("Expected JSON list of records from data.gov.my API")


def _next_day_str(iso_date: str) -> str:
    d = date.fromisoformat(iso_date[:10])
    return (d + timedelta(days=1)).isoformat()


def fetch_catalogue_records(
    client: httpx.Client,
    dataset_id: str,
    *,
    api_url: str = DATAGOVMY_API_URL,
    filters: Mapping[str, str] | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    date_column: str | None = "date",
    page_size: int = 500,
    max_pages: int = 20,
) -> tuple[list[dict[str, object]], str, int]:
    """Fetch records from data.gov.my API, paging forward by `date_start` when full pages return."""
    all_records: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    cursor_start = date_start
    last_resolved_url = api_url
    last_status = 200

    for _ in range(max_pages):
        params = build_catalogue_params(
            dataset_id,
            filters=filters,
            date_start=cursor_start if date_column else None,
            date_end=date_end if date_column else None,
            date_column=date_column or "date",
            sort=date_column if date_column else None,
            limit=page_size,
        )
        res = fetch_url(client, api_url, params=params)
        last_resolved_url = res.resolved_url
        last_status = res.http_status
        batch = _extract_json_records(res.content)

        for row in batch:
            key = json.dumps(row, sort_keys=True)
            if key not in seen_keys:
                seen_keys.add(key)
                all_records.append(row)

        if len(batch) < page_size or not date_column:
            break

        batch_dates = [str(r[date_column])[:10] for r in batch if r.get(date_column) is not None]
        if not batch_dates:
            break
        max_date = max(batch_dates)
        next_cursor = _next_day_str(max_date)
        if cursor_start is not None and next_cursor <= cursor_start:
            break
        cursor_start = next_cursor

    return all_records, last_resolved_url, last_status


def _load_tabular_payload(payload: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    try:
        if lower.endswith(".parquet"):
            return pd.read_parquet(io.BytesIO(payload))
        if lower.endswith(".csv"):
            return pd.read_csv(io.BytesIO(payload))
        if lower.endswith(".json"):
            records = _extract_json_records(payload)
            return pd.DataFrame(records)
    except SnapshotValidationError:
        raise
    except Exception as exc:
        raise SnapshotValidationError(f"Failed to parse {filename}: {exc}") from exc
    raise SnapshotValidationError(f"Unsupported snapshot file extension: {filename}")


def parse_exchangerates(
    payload: bytes,
    filename: str = "daily_1700.parquet",
) -> pd.DataFrame:
    """Validate and extract daily middle USD/MYR exchange rates."""
    df = _load_tabular_payload(payload, filename)
    required = {"date", "rate_type", "USD"}
    if not required.issubset(df.columns):
        missing = sorted(required - set(df.columns))
        raise SnapshotValidationError(f"exchangerates_daily_1700 missing columns: {missing}")

    sub = df[df["rate_type"].astype(str) == "middle"][["date", "rate_type", "USD"]].copy()
    sub["date"] = pd.to_datetime(sub["date"]).dt.strftime("%Y-%m-%d")
    sub["USD"] = pd.to_numeric(sub["USD"], errors="coerce")
    sub = sub.dropna(subset=["date", "USD"]).sort_values("date").reset_index(drop=True)
    if sub.empty:
        raise SnapshotValidationError("No middle USD/MYR rows in exchangerates_daily_1700")
    if (sub["USD"] <= 0).any():
        raise SnapshotValidationError("Non-positive USD/MYR rate in exchangerates_daily_1700")
    return sub


def parse_ppi_sitc(
    payload: bytes,
    filename: str = "ppi_sitc.csv",
    *,
    snapshot_id: str = "",
    available_from: str = "",
) -> pd.DataFrame:
    """Validate and extract monthly PPI SITC section 4 ('abs') series (`ppi_oilsfats_my`)."""
    df = _load_tabular_payload(payload, filename)
    required = {"series", "date", "section", "index"}
    if not required.issubset(df.columns):
        missing = sorted(required - set(df.columns))
        raise SnapshotValidationError(f"ppi_sitc missing columns: {missing}")

    sub = df[(df["series"].astype(str) == "abs") & (df["section"].astype(str) == "4")][
        ["date", "index"]
    ].copy()
    if sub.empty:
        raise SnapshotValidationError("No section 4 'abs' rows found in ppi_sitc")

    sub["month"] = pd.to_datetime(sub["date"]).dt.strftime("%Y-%m-01")
    sub["value"] = pd.to_numeric(sub["index"], errors="coerce")
    if sub["value"].isna().any() or (sub["value"] <= 0).any():
        raise SnapshotValidationError("Invalid or non-positive index values in ppi_sitc section 4")

    sub = sub.sort_values("month").reset_index(drop=True)
    if sub["month"].duplicated().any():
        raise SnapshotValidationError("Duplicate months in ppi_sitc section 4")

    # Latest 3 months are revisable per DOSM documentation
    n = len(sub)
    is_prov = [idx >= max(0, n - 3) for idx in range(n)]
    return pd.DataFrame(
        {
            "series_id": "ppi_oilsfats_my",
            "month": sub["month"].astype(str),
            "value": sub["value"].astype(float),
            "available_from": available_from,
            "snapshot_id": snapshot_id,
            "is_provisional": is_prov,
        }
    )


def parse_trade_sitc(
    payload: bytes,
    filename: str = "trade_sitc_1d.parquet",
    *,
    snapshot_id: str = "",
    available_from: str = "",
) -> pd.DataFrame:
    """Validate and extract monthly SITC section 4 exports (`exports_sitc4`)."""
    df = _load_tabular_payload(payload, filename)
    required = {"date", "section", "exports", "imports"}
    if not required.issubset(df.columns):
        missing = sorted(required - set(df.columns))
        raise SnapshotValidationError(f"trade_sitc_1d missing columns: {missing}")

    sub = df[df["section"].astype(str) == "4"][["date", "exports", "imports"]].copy()
    if sub.empty:
        raise SnapshotValidationError("No section 4 rows found in trade_sitc_1d")

    sub["month"] = pd.to_datetime(sub["date"]).dt.strftime("%Y-%m-01")
    sub["value"] = pd.to_numeric(sub["exports"], errors="coerce")
    if sub["value"].isna().any() or (sub["value"] <= 0).any():
        raise SnapshotValidationError("Invalid or non-positive exports in trade_sitc_1d section 4")

    sub = sub.sort_values("month").reset_index(drop=True)
    if sub["month"].duplicated().any():
        raise SnapshotValidationError("Duplicate months in trade_sitc_1d section 4")

    # Latest 2 months are provisional per DOSM documentation
    n = len(sub)
    is_prov = [idx >= max(0, n - 2) for idx in range(n)]
    return pd.DataFrame(
        {
            "series_id": "exports_sitc4",
            "month": sub["month"].astype(str),
            "value": sub["value"].astype(float),
            "available_from": available_from,
            "snapshot_id": snapshot_id,
            "is_provisional": is_prov,
        }
    )


def parse_sitc_lookup(payload: bytes) -> pd.DataFrame:
    """Validate the SITC section lookup JSON and confirm section 4 description."""
    records = _extract_json_records(payload)
    df = pd.DataFrame(records)
    required = {"section", "desc_en"}
    if not required.issubset(df.columns):
        missing = sorted(required - set(df.columns))
        raise SnapshotValidationError(f"sitc lookup missing columns: {missing}")

    sec4 = df[df["section"].astype(str) == "4"]
    if sec4.empty:
        raise SnapshotValidationError("Section 4 missing from sitc lookup")
    desc = str(sec4["desc_en"].iloc[0]).lower()
    if "oils" not in desc:
        raise SnapshotValidationError(
            f"Unexpected section 4 description: {sec4['desc_en'].iloc[0]!r}"
        )
    return df


def validate_dataset_payload(dataset_id: str, payload: bytes, filename: str) -> int:
    """Validate raw payload for any of the four supported data.gov.my datasets and return row count."""
    if dataset_id == "exchangerates_daily_1700":
        return len(parse_exchangerates(payload, filename))
    if dataset_id == "ppi_sitc":
        return len(parse_ppi_sitc(payload, filename))
    if dataset_id == "trade_sitc_1d":
        return len(parse_trade_sitc(payload, filename))
    if dataset_id == "sitc":
        return len(parse_sitc_lookup(payload))
    raise ValueError(f"Unknown dataset_id: {dataset_id}")


def _read_existing_records(
    raw_root: Path,
    manifest: SnapshotManifest,
    dataset_id: str,
) -> list[dict[str, object]]:
    from palmguard.ingest.snapshots import get_snapshot_dir

    parts = manifest.snapshot_id.split(".")
    date_part = parts[2] if len(parts) >= 4 else manifest.retrieved_at_utc[:10]
    path = (
        get_snapshot_dir(raw_root, manifest.source, manifest.dataset, date_part) / manifest.filename
    )
    if not path.is_file():
        return []
    payload = path.read_bytes()
    df = _load_tabular_payload(payload, manifest.filename)
    if dataset_id == "exchangerates_daily_1700":
        df = df[df["rate_type"].astype(str) == "middle"][["date", "rate_type", "USD"]].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    elif dataset_id == "ppi_sitc":
        df = df[(df["series"].astype(str) == "abs") & (df["section"].astype(str) == "4")][
            ["series", "date", "section", "index"]
        ].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["section"] = df["section"].astype(str)
    elif dataset_id == "trade_sitc_1d":
        df = df[df["section"].astype(str) == "4"][["date", "section", "exports", "imports"]].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["section"] = df["section"].astype(str)
    return df.to_dict(orient="records")


def _merge_records(
    base_records: list[dict[str, object]],
    new_records: list[dict[str, object]],
    date_column: str | None,
) -> list[dict[str, object]]:
    if not base_records:
        return new_records
    if not date_column:
        return new_records
    by_date: dict[str, dict[str, object]] = {}
    for row in base_records:
        d = str(row.get(date_column, ""))[:10]
        if d:
            by_date[d] = row
    for row in new_records:
        d = str(row.get(date_column, ""))[:10]
        if d:
            by_date[d] = row
    return [by_date[k] for k in sorted(by_date)]


def ingest_datagovmy_dataset(
    raw_root: Path,
    client: httpx.Client,
    dataset_id: str,
    *,
    mode: Literal["auto", "backfill", "incremental"] = "auto",
    date_start: str | None = None,
    lookback_days: int = 120,
    page_size: int = 500,
    retrieved_at_utc: str | None = None,
) -> SnapshotWriteResult:
    """Ingest a data.gov.my dataset via bulk backfill or incremental API query."""
    if dataset_id not in DATASET_SPECS:
        raise ValueError(f"Unsupported data.gov.my dataset: {dataset_id}")
    spec = DATASET_SPECS[dataset_id]

    existing = latest_snapshot(raw_root, spec.source, spec.dataset)
    effective_mode = mode
    if effective_mode == "auto":
        effective_mode = "backfill" if (existing is None and spec.bulk_url) else "incremental"

    if effective_mode == "backfill" and spec.bulk_url is not None:
        res = fetch_url(client, spec.bulk_url)
        row_count = validate_dataset_payload(dataset_id, res.content, spec.bulk_filename)
        return write_snapshot(
            raw_root,
            source=spec.source,
            dataset=spec.dataset,
            payload=res.content,
            filename=spec.bulk_filename,
            request_url=spec.bulk_url,
            resolved_url=res.resolved_url,
            http_status=res.http_status,
            retrieved_at_utc=retrieved_at_utc or res.retrieved_at_utc,
            row_count=row_count,
        )

    base_records: list[dict[str, object]] = []
    effective_date_start = date_start
    if existing is not None and spec.date_column:
        base_records = _read_existing_records(raw_root, existing, dataset_id)
        if effective_date_start is None and base_records:
            max_date_str = max(str(r[spec.date_column])[:10] for r in base_records)
            lookback = date.fromisoformat(max_date_str) - timedelta(days=lookback_days)
            effective_date_start = lookback.isoformat()

    records, resolved_url, status_code = fetch_catalogue_records(
        client,
        dataset_id,
        filters=spec.default_filters,
        date_start=effective_date_start,
        date_column=spec.date_column,
        page_size=page_size,
    )
    merged = _merge_records(base_records, records, spec.date_column)
    if existing is not None and base_records and merged == base_records:
        from palmguard.ingest.snapshots import get_snapshot_dir

        parts = existing.snapshot_id.split(".")
        existing_date = parts[2] if len(parts) >= 4 else existing.retrieved_at_utc[:10]
        existing_dir = get_snapshot_dir(raw_root, existing.source, existing.dataset, existing_date)
        return SnapshotWriteResult(
            manifest=existing,
            status="no_change",
            snapshot_dir=existing_dir,
            payload_path=existing_dir / existing.filename,
            manifest_path=existing_dir / "manifest.json",
        )

    payload_bytes = (json.dumps(merged, indent=2, sort_keys=True) + "\n").encode("utf-8")
    filename = f"{dataset_id}.json"
    row_count = validate_dataset_payload(dataset_id, payload_bytes, filename)
    return write_snapshot(
        raw_root,
        source=spec.source,
        dataset=spec.dataset,
        payload=payload_bytes,
        filename=filename,
        request_url=f"{DATAGOVMY_API_URL}?id={dataset_id}",
        resolved_url=resolved_url,
        http_status=status_code,
        retrieved_at_utc=retrieved_at_utc,
        row_count=row_count,
    )


def ingest_all_datagovmy(
    raw_root: Path,
    client: httpx.Client,
    *,
    mode: Literal["auto", "backfill", "incremental"] = "auto",
) -> dict[str, SnapshotWriteResult]:
    """Ingest all four data.gov.my datasets in deterministic order."""
    results: dict[str, SnapshotWriteResult] = {}
    for ds_id in ("exchangerates_daily_1700", "ppi_sitc", "trade_sitc_1d", "sitc"):
        results[ds_id] = ingest_datagovmy_dataset(raw_root, client, ds_id, mode=mode)
    return results
