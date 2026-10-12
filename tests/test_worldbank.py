"""Tests for the World Bank Pink Sheet ingestor and xlsx parser (Task T03)."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import openpyxl
import pytest

from palmguard.http import create_http_client
from palmguard.ingest.snapshots import SnapshotValidationError
from palmguard.ingest.worldbank import (
    WORLDBANK_LANDING_URL,
    ingest_worldbank_pink_sheet,
    parse_pink_sheet_xlsx,
    resolve_monthly_xlsx_url,
)


def _build_fixture_xlsx(
    *,
    palm_unit: str = "($/mt)",
    include_palm: bool = True,
    palm_values: list[object] | None = None,
) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Monthly Prices"
    ws.append(["World Bank Commodity Price Data (The Pink Sheet)"])
    ws.append(["monthly prices in nominal US dollars"])
    ws.append(["(monthly series are available only in nominal US dollars)"])
    ws.append(["Updated on October 02, 2026"])

    headers = ["", "Crude oil, average", "Crude oil, Brent", "Soybean oil"]
    units = ["", "($/bbl)", "($/bbl)", "($/mt)"]
    if include_palm:
        headers.append("Palm oil")
        units.append(palm_unit)
    ws.append(headers)
    ws.append(units)

    p_vals = palm_values if palm_values is not None else [910.0, 925.5, 940.0]
    months = ["2026M07", "2026M08", "2026M09"]
    brents = [83.4, 90.9, 116.8]
    soyoils = [1658.0, 1639.0, 1615.0]
    for idx, m in enumerate(months):
        row = [m, brents[idx], brents[idx], soyoils[idx]]
        if include_palm:
            row.append(p_vals[idx])
        ws.append(row)

    desc = wb.create_sheet("Description")
    desc.append(
        [
            "   *",
            (
                "Palm oil (Malaysia), from January 2026, RBD, average export price FOB;"
                "February-December 2025, Crude, DAP; November 2024-January 2025, 5% Bulk, "
                "CIF North West Europe; January 2021 to October 2024, RBD, FOB Malaysia Ports; "
                "December 2001 to December 2020, RBD, CIF Rotterdam; previously Malaysia 5%, "
                "c.i.f. N.W. Europe, bulk, nearest forward ."
            ),
            "S&P Global; Bloomberg; Oil World; USDA; World Bank.",
        ]
    )
    desc.append(["Crude oil, UK Brent 38` API.", "Bloomberg; EIG; OPEC; World Bank."])
    desc.append(
        [
            "   *",
            "Soybean oil, from January 2025, U.S. Soybean Oil, Crude Degummed, FOB U.S. Gulf.",
            "World Bank.",
        ]
    )
    desc.append(["October 2026: Replacement series for Palm oil from January 2026."])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_resolve_monthly_xlsx_url() -> None:
    html = """
    <html><body>
      <a href="https://thedocs.worldbank.org/en/doc/abc123/related/CMO-Historical-Data-Monthly.xlsx">
        Monthly prices
      </a>
    </body></html>
    """
    url = resolve_monthly_xlsx_url(html)
    assert (
        url
        == "https://thedocs.worldbank.org/en/doc/abc123/related/CMO-Historical-Data-Monthly.xlsx"
    )

    with pytest.raises(SnapshotValidationError, match="Could not find"):
        resolve_monthly_xlsx_url("<html><body>No links here</body></html>")


def test_parse_pink_sheet_xlsx_extracts_series_and_descriptions() -> None:
    payload = _build_fixture_xlsx()
    df, meta = parse_pink_sheet_xlsx(payload, snapshot_id="wb.1", available_from="2026-10-11")

    assert set(df["series_id"].unique()) == {"palm_wb_usd", "brent_wb_usd", "soyoil_wb_usd"}
    assert len(df) == 9
    assert meta.updated_note == "Updated on October 02, 2026"
    assert meta.columns_found == {
        "Palm oil": "($/mt)",
        "Crude oil, Brent": "($/bbl)",
        "Soybean oil": "($/mt)",
    }
    assert meta.start_months["palm_wb_usd"] == "2026-07-01"
    assert meta.end_months["palm_wb_usd"] == "2026-09-01"
    assert meta.row_counts["palm_wb_usd"] == 3
    assert "RBD, average export price FOB" in meta.descriptions["Palm oil"]
    assert "Replacement series for Palm oil" in meta.descriptions["Palm oil revision note"]


def test_parse_pink_sheet_rejects_bad_schema_or_values() -> None:
    # Missing Palm oil column
    with pytest.raises(SnapshotValidationError, match="Required columns"):
        parse_pink_sheet_xlsx(_build_fixture_xlsx(include_palm=False))

    # Wrong unit
    with pytest.raises(SnapshotValidationError, match="Unexpected unit"):
        parse_pink_sheet_xlsx(_build_fixture_xlsx(palm_unit="($/kg)"))

    # Non-positive value
    with pytest.raises(SnapshotValidationError, match="Non-positive value"):
        parse_pink_sheet_xlsx(_build_fixture_xlsx(palm_values=[900.0, -5.0, 910.0]))


def test_ingest_worldbank_pink_sheet_writes_snapshot_and_is_idempotent(tmp_path: Path) -> None:
    xlsx_bytes = _build_fixture_xlsx()
    xlsx_url = "https://thedocs.worldbank.org/en/doc/hash/related/CMO-Historical-Data-Monthly.xlsx"
    landing_html = f'<a href="{xlsx_url}">Download Monthly XLS</a>'.encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == WORLDBANK_LANDING_URL:
            return httpx.Response(200, content=landing_html)
        if str(request.url) == xlsx_url:
            return httpx.Response(200, content=xlsx_bytes)
        return httpx.Response(404)

    with create_http_client(transport=httpx.MockTransport(handler)) as client:
        res1, df1, meta1 = ingest_worldbank_pink_sheet(
            tmp_path,
            client,
            retrieved_at_utc="2026-10-11T09:00:00+00:00",
        )
        res2, df2, _ = ingest_worldbank_pink_sheet(
            tmp_path,
            client,
            retrieved_at_utc="2026-10-12T09:00:00+00:00",
        )

    assert res1.status == "written"
    assert res1.manifest.row_count == 9
    assert res1.manifest_path.is_file()
    assert res2.status == "no_change"
    assert res2.manifest.snapshot_id == res1.manifest.snapshot_id
    assert (df1["snapshot_id"] == res1.manifest.snapshot_id).all()
    assert len(df2) == 9
    assert meta1.row_counts["palm_wb_usd"] == 3
