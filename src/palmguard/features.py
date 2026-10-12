"""Feature and panel generation executing DuckDB SQL queries (Task T07, T08)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from palmguard.contracts import validate_monthly_series_df
from palmguard.ingest.datagovmy import (
    parse_exchangerates,
)
from palmguard.ingest.snapshots import (
    SnapshotValidationError,
    get_snapshot_dir,
    list_snapshots,
)
from palmguard.ingest.worldbank import parse_pink_sheet_xlsx

DEFAULT_SQL_DIR = Path("queries")


def _read_snapshot_file(
    raw_root: Path, source: str, dataset: str, date_str: str, filename: str
) -> bytes:
    p = get_snapshot_dir(raw_root, source, dataset, date_str) / filename
    if not p.is_file():
        raise FileNotFoundError(f"Snapshot payload not found: {p}")
    return p.read_bytes()


def load_raw_tables_into_duckdb(
    conn: duckdb.DuckDBPyConnection,
    raw_root: Path,
    as_of: str,
) -> None:
    """Load all relevant raw snapshot payloads into memory tables in DuckDB."""
    manifest_rows: list[dict[str, object]] = []

    # 1. World Bank Pink Sheet
    wb_snaps = list_snapshots(raw_root, "worldbank", "pink_sheet")
    wb_records: list[dict[str, object]] = []
    for snap in wb_snaps:
        manifest_rows.append(
            {
                "source": snap.source,
                "dataset": snap.dataset,
                "snapshot_id": snap.snapshot_id,
                "available_from": snap.retrieved_at_utc[:10],
            }
        )
        if snap.retrieved_at_utc[:10] <= as_of:
            p_bytes = _read_snapshot_file(
                raw_root, snap.source, snap.dataset, snap.snapshot_id.split(".")[2], snap.filename
            )
            df, _ = parse_pink_sheet_xlsx(
                p_bytes, snapshot_id=snap.snapshot_id, available_from=snap.retrieved_at_utc[:10]
            )
            wb_records.extend(df.to_dict(orient="records"))

    # 2. BNM Exchange Rates
    exr_snaps = list_snapshots(raw_root, "bnm", "exchangerates_daily_1700")
    exr_records: list[dict[str, object]] = []
    for snap in exr_snaps:
        manifest_rows.append(
            {
                "source": snap.source,
                "dataset": snap.dataset,
                "snapshot_id": snap.snapshot_id,
                "available_from": snap.retrieved_at_utc[:10],
            }
        )
        if snap.retrieved_at_utc[:10] <= as_of:
            p_bytes = _read_snapshot_file(
                raw_root, snap.source, snap.dataset, snap.snapshot_id.split(".")[2], snap.filename
            )
            df_exr = parse_exchangerates(p_bytes, snap.filename)
            exr_records.extend(df_exr.to_dict(orient="records"))

    # 3. DOSM PPI
    ppi_snaps = list_snapshots(raw_root, "dosm", "ppi_sitc")
    ppi_records: list[dict[str, object]] = []
    for snap in ppi_snaps:
        manifest_rows.append(
            {
                "source": snap.source,
                "dataset": snap.dataset,
                "snapshot_id": snap.snapshot_id,
                "available_from": snap.retrieved_at_utc[:10],
            }
        )
        if snap.retrieved_at_utc[:10] <= as_of:
            p_bytes = _read_snapshot_file(
                raw_root, snap.source, snap.dataset, snap.snapshot_id.split(".")[2], snap.filename
            )
            if snap.filename.endswith(".json"):
                raw_list = json.loads(p_bytes.decode("utf-8"))
                for row in raw_list:
                    ppi_records.append(
                        {
                            "series": str(row.get("series", "")),
                            "date": str(row.get("date", ""))[:10],
                            "section": str(row.get("section", "")),
                            "index": float(row.get("index", 0.0)),
                        }
                    )
            else:
                df_ppi = pd.read_csv(
                    Path(
                        get_snapshot_dir(
                            raw_root, snap.source, snap.dataset, snap.snapshot_id.split(".")[2]
                        )
                        / snap.filename
                    )
                )
                for _, r in df_ppi.iterrows():
                    ppi_records.append(
                        {
                            "series": str(r["series"]),
                            "date": str(r["date"])[:10],
                            "section": str(r["section"]),
                            "index": float(r["index"]),
                        }
                    )

    # 4. DOSM Trade
    trd_snaps = list_snapshots(raw_root, "dosm", "trade_sitc_1d")
    trd_records: list[dict[str, object]] = []
    for snap in trd_snaps:
        manifest_rows.append(
            {
                "source": snap.source,
                "dataset": snap.dataset,
                "snapshot_id": snap.snapshot_id,
                "available_from": snap.retrieved_at_utc[:10],
            }
        )
        if snap.retrieved_at_utc[:10] <= as_of:
            p_bytes = _read_snapshot_file(
                raw_root, snap.source, snap.dataset, snap.snapshot_id.split(".")[2], snap.filename
            )
            if snap.filename.endswith(".json"):
                raw_list = json.loads(p_bytes.decode("utf-8"))
                for row in raw_list:
                    trd_records.append(
                        {
                            "date": str(row.get("date", ""))[:10],
                            "section": str(row.get("section", "")),
                            "exports": float(row.get("exports", 0.0)),
                            "imports": float(row.get("imports", 0.0)),
                        }
                    )
            else:
                df_trd = pd.read_parquet(
                    Path(
                        get_snapshot_dir(
                            raw_root, snap.source, snap.dataset, snap.snapshot_id.split(".")[2]
                        )
                        / snap.filename
                    )
                )
                for _, r in df_trd.iterrows():
                    trd_records.append(
                        {
                            "date": str(r["date"])[:10],
                            "section": str(r["section"]),
                            "exports": float(r["exports"]),
                            "imports": float(r["imports"]),
                        }
                    )

    conn.register(
        "raw_manifests",
        pd.DataFrame(manifest_rows)
        if manifest_rows
        else pd.DataFrame(columns=["source", "dataset", "snapshot_id", "available_from"]),
    )
    conn.register(
        "raw_pink_sheet",
        pd.DataFrame(wb_records)
        if wb_records
        else pd.DataFrame(columns=["series_id", "month", "value"]),
    )
    conn.register(
        "raw_exchangerates",
        pd.DataFrame(exr_records)
        if exr_records
        else pd.DataFrame(columns=["date", "rate_type", "USD"]),
    )
    conn.register(
        "raw_ppi",
        pd.DataFrame(ppi_records)
        if ppi_records
        else pd.DataFrame(columns=["series", "date", "section", "index"]),
    )
    conn.register(
        "raw_trade",
        pd.DataFrame(trd_records)
        if trd_records
        else pd.DataFrame(columns=["date", "section", "exports", "imports"]),
    )


def build_monthly_panel_df(
    raw_root: Path,
    *,
    as_of: str,
    sql_path: Path = DEFAULT_SQL_DIR / "monthly_panel.sql",
    conn: duckdb.DuckDBPyConnection | None = None,
) -> pd.DataFrame:
    """Execute monthly_panel.sql in DuckDB as of a vintage date and validate output."""
    if not sql_path.is_file():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")
    query = sql_path.read_text(encoding="utf-8")

    own_conn = conn is None
    c = duckdb.connect(":memory:") if own_conn else conn
    try:
        load_raw_tables_into_duckdb(c, raw_root, as_of)
        df = c.execute(query, {"as_of": as_of}).df()
    finally:
        if own_conn:
            c.close()

    if df.empty:
        raise SnapshotValidationError(f"Monthly panel query returned 0 rows for as_of={as_of}")

    # Validate each canonical series in output
    for s_id in df["series_id"].unique():
        s_df = df[df["series_id"] == s_id].reset_index(drop=True)
        validate_monthly_series_df(s_df, expected_series_id=s_id, min_rows=1)

    return df.sort_values(["series_id", "month"]).reset_index(drop=True)


def build_features_df(
    panel_df: pd.DataFrame,
    *,
    target_series: str,
    sql_path: Path = DEFAULT_SQL_DIR / "features.sql",
    conn: duckdb.DuckDBPyConnection | None = None,
) -> pd.DataFrame:
    """Execute features.sql over the panel DataFrame for a specified target series."""
    if not sql_path.is_file():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")
    query = sql_path.read_text(encoding="utf-8")

    own_conn = conn is None
    c = duckdb.connect(":memory:") if own_conn else conn
    try:
        c.register("panel", panel_df)
        df = c.execute(query, {"target_series": target_series}).df()
    finally:
        if own_conn:
            c.close()

    if df.empty:
        raise SnapshotValidationError(
            f"Feature query returned 0 rows for target_series={target_series}"
        )

    return df.sort_values("origin_month").reset_index(drop=True)
