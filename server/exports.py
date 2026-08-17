"""CSV exports: the analyst's work product as a file, not a chat payload.

Every cap the MCP surface carries — 200 rows on `run_sql`, the evidence
window, the artifact payload's trim — exists because tool responses land in
the model's context window. An export has no such constraint, so it must not
travel that way: `export_data` mints a capability URL, the bytes are
assembled *here* and streamed down `GET /export/{token}/{filename}`, and the
tool returns a URL plus a row count — a few hundred bytes of context no
matter how large the file is. Same discipline as the upload lane
(server/uploads.py), pointed the other way.

Assembly happens at fetch time rather than mint time, so nothing sits at
rest: the token carries a run_id or a validated query, and the durable copy
is the run record in Postgres. An expired link costs one cheap re-mint, never
a recomputation — and re-minting requires a session, which is the point. This
is a deliverable an analyst hands over, not a feed.
"""
import csv
import io
import zipfile
from datetime import datetime, timezone

from utils.schemas import EXPLORATION_SCHEMAS
from utils.sql_guard import run_guarded

# Export-scale caps. Deliberately far above the chat caps (the bytes don't
# touch context) and deliberately finite (a boundless query export is a data
# feed wearing a tool name).
EXPORT_ROW_CAP = 100_000
EXPORT_SIZE_CAP_BYTES = 64 * 1024 * 1024
EXPORT_TIMEOUT_MS = 30_000

KINDS = ("volumes", "parameters", "query", "bundle")

# Physical + net volumes only. Revenue, tax and cashflow columns live in the
# same schedule but a volumes export that quietly carried them would be an
# economics export; add a kind if that's ever wanted.
_VOLUME_COLS = ("oil_bbl", "gas_mcf", "net_oil", "net_gas")

# Every column the schedule carries. The `bundle` kind ships all of them in one
# wide table: same grain as volumes, so splitting physical from financial would
# only force a join back together. Kept as an explicit tuple rather than read
# off the schedule so the export has a stated contract; pinned to the
# orchestrator's `_SCHEDULE_COLS` by tests/test_exports.py.
_CASHFLOW_COLS = (
    "oil_bbl", "gas_mcf", "net_oil", "net_gas", "gross_rev", "net_rev",
    "sev_tax", "gpt", "capex", "opex", "net_cashflow",
)

_PARAM_HEADER = (
    "well_api", "stream", "qi_committed", "qi_asserted", "di", "b",
    "terminal_di_monthly", "switch_month_from_anchor", "anchor_month",
    "uptime_factor", "status", "entry_id", "rationale",
)


class ExportError(RuntimeError):
    """Anything that makes an export impossible to assemble honestly."""


def to_csv(header, rows) -> str:
    """Header tuple + row iterable → CSV text. `\\r\\n` per RFC 4180, which is
    what every database COPY and spreadsheet importer expects."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(list(header))
    for row in rows:
        w.writerow(list(row))
    return buf.getvalue()


def filename_for(kind: str, *, run_id: str = "", label: str = "") -> str:
    """A name the browser can save and a human can recognise a week later."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    stem = (label or "").strip().lower()
    stem = "".join(c if (c.isalnum() or c in "-_") else "-" for c in stem).strip("-")
    parts = ["crudecode", kind]
    if stem:
        parts.append(stem[:40])
    elif run_id:
        parts.append(run_id[:8])
    parts.append(stamp)
    return "-".join(parts) + (".zip" if kind == "bundle" else ".csv")


def media_type_for(kind: str) -> str:
    """What the route should label the bytes as."""
    return "application/zip" if kind == "bundle" else "text/csv; charset=utf-8"


def _well_month_csv(economics: dict, cols: tuple[str, ...]) -> tuple[str, int]:
    """Walk a run's per-well schedule into a well x month table over `cols`.

    Rows are emitted for every month on the axis including pre-online zeros:
    the export is rectangular on purpose, so a load into someone else's
    database doesn't have to guess at gaps. A column the schedule doesn't
    carry reads as 0.0 rather than exploding — the header is the contract.
    """
    schedule = (economics or {}).get("schedule") or {}
    by_well = schedule.get("by_well")
    if not by_well:
        omitted = schedule.get("by_well_omitted")
        raise ExportError(
            f"this run has no per-well schedule to export ({omitted})"
            if omitted else
            "this run has no economics stage yet — run run_valuation first"
        )
    months = schedule.get("months") or []

    def _rows():
        for api in sorted(by_well):
            cols_for_well = by_well[api]
            for i, month in enumerate(months):
                yield (
                    api, month, i,
                    *(cols_for_well.get(c, [])[i]
                      if i < len(cols_for_well.get(c, [])) else 0.0
                      for c in cols),
                )

    rows = list(_rows())
    return to_csv(("well_api", "month", "month_index", *cols), rows), len(rows)


def build_volumes_csv(economics: dict) -> tuple[str, int]:
    """Monthly gross + net oil and gas, one row per well per month, over the
    run's full economic horizon.

    Gross (`oil_bbl`/`gas_mcf`) is the committed curve evaluated forward —
    physical volumes, before any interest is applied. Net columns carry the
    same volumes scaled by each well's revenue interest, so a per-well
    ownership deal rolls up correctly.
    """
    return _well_month_csv(economics, _VOLUME_COLS)


def build_cashflow_csv(economics: dict) -> tuple[str, int]:
    """The whole schedule, one row per well per month: physical volumes, net
    volumes, and every financial line item the engine computed.

    `net_cashflow = net_rev - sev_tax - gpt - capex - opex` holds row by row,
    so the file is an audit trail rather than a summary — the NPV on the deal
    sheet is this column discounted. Ships inside `bundle` only; the standalone
    `volumes` kind stays narrow on purpose.
    """
    return _well_month_csv(economics, _CASHFLOW_COLS)


def build_parameters_csv(forecast: dict) -> tuple[str, int]:
    """The committed decline parameters, one row per well per stream.

    `qi_committed` is the rate the calculator actually projects from — already
    scaled by the entry's uptime factor and, for cohort assertions, by the
    member's pro-rata share. `qi_asserted` is what Claude asserted before that
    scaling. Reproducing a forecast takes `qi_committed`, `di`, `b`, the
    terminal switch, and `anchor_month`; the two qi columns are both here so
    the scaling is auditable rather than implied.
    """
    forecasts = (forecast or {}).get("forecasts") or {}
    if not forecasts:
        raise ExportError("this run has no forecast stage yet — run forecast_wells first")

    rows = []
    for api in sorted(forecasts):
        fc = forecasts[api]
        assertion = fc.get("assertion") or {}
        asserted = assertion.get("asserted") or {}
        for stream in ("oil", "gas"):
            curve = (fc.get(stream) or {}).get("curve")
            if not curve:
                continue
            a = asserted.get(stream) or {}
            rows.append((
                api,
                stream,
                curve.get("qi", curve.get("qi_peak")),
                a.get("qi"),
                curve.get("di"),
                curve.get("b"),
                curve.get("terminal_di_monthly"),
                curve.get("switch_month_from_peak"),
                fc.get("anchor_month"),
                assertion.get("uptime_factor"),
                fc.get("status"),
                assertion.get("entry_id"),
                assertion.get("rationale"),
            ))
    if not rows:
        raise ExportError("no committed curves found on this run's forecast stage")
    return to_csv(_PARAM_HEADER, rows), len(rows)


def build_query_csv(sql: str, *, schema: str = "public") -> tuple[str, int]:
    """A `run_sql` query re-run at export scale.

    Same guard stack as the chat tool — SELECT-only, schema-allowlisted,
    statement timeout — with the row and size caps raised, since the result
    goes to a file instead of the context window. Re-run rather than cached so
    the file can never be stale relative to the query it claims to answer.
    """
    result = run_guarded(
        sql,
        schema=schema,
        allowed_schemas=EXPLORATION_SCHEMAS,
        row_cap=EXPORT_ROW_CAP,
        size_cap_bytes=EXPORT_SIZE_CAP_BYTES,
        timeout_ms=EXPORT_TIMEOUT_MS,
    )
    rows = result.get("rows") or []
    if not rows:
        raise ExportError("query returned no rows — nothing to export")
    header = tuple(rows[0].keys())
    return to_csv(header, ([r.get(c) for c in header] for r in rows)), len(rows)


_README = """Crude Code — data package
Run:       {run_id}
Generated: {stamp}

FILES

  wells_monthly.csv   One row per well per month, over the run's full economic
                      horizon. Physical volumes (oil_bbl, gas_mcf), the same
                      volumes at revenue interest (net_oil, net_gas), and the
                      cashflow line items, where row by row:

                        net_cashflow = net_rev - sev_tax - gpt - capex - opex

                      Volumes in bbl and mcf, money in dollars, months are
                      first-of-month dates on a continuous axis (pre-online
                      months are present and zero).
{parameters_doc}
WHAT THIS IS

A snapshot. These numbers are the projection from the decline curves committed
during the session that produced this run, priced against the deck recorded on
it. Nothing here refreshes — next month's actual production does not change
this file, which is exactly what keeps it consistent with the deal sheet it
came from. For updated numbers, run the valuation again.
"""

_README_PARAMETERS = """
  parameters.csv      The committed decline curves, one row per well per
                      stream — the reproducibility record. qi_committed is the
                      rate the calculator projected from (already scaled by
                      uptime factor and cohort share); qi_asserted is the value
                      before that scaling, so the scaling is auditable.
"""


def build_bundle_zip(economics: dict, forecast: dict | None,
                     *, run_id: str = "") -> tuple[bytes, int]:
    """Several CSVs and a README, zipped in memory.

    The generous end of the lane: rather than making the user name the columns
    they want, hand over everything the run holds and let them keep what they
    need. Assembly stays at fetch time like every other kind — the zip is built
    here and streamed, never stored.

    The economics stage is required (it is what `wells_monthly.csv` is made
    of); parameters ride along when the forecast stage is readable, so a run
    that somehow lost it still yields a bundle rather than an error.
    """
    members: list[tuple[str, str]] = []
    rows_total = 0

    cashflow, n = build_cashflow_csv(economics)
    members.append(("wells_monthly.csv", cashflow))
    rows_total += n

    try:
        parameters, n = build_parameters_csv(forecast or {})
    except ExportError:
        parameters = None
    else:
        members.append(("parameters.csv", parameters))
        rows_total += n

    members.append(("README.txt", _README.format(
        run_id=run_id or "(unknown)",
        stamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        parameters_doc=_README_PARAMETERS if parameters else "",
    )))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in members:
            z.writestr(name, text)
    return buf.getvalue(), rows_total


def assemble(kind: str, meta: dict, *, run_store=None) -> tuple[str | bytes, int]:
    """Dispatch a minted export to its builder. Returns `(body, rows)` — text
    for the CSV kinds, bytes for `bundle`; the route labels it via
    `media_type_for`.

    `meta` is the token grant's payload: `run_id` for the run-derived kinds,
    `sql`/`schema` for a query. `run_store` is injected so the route stays
    testable without a database.
    """
    if kind not in KINDS:
        raise ExportError(f"unknown export kind {kind!r}; expected one of {list(KINDS)}")

    if kind == "query":
        return build_query_csv(meta.get("sql") or "", schema=meta.get("schema") or "public")

    run_id = meta.get("run_id")
    if not run_id:
        raise ExportError(f"export kind {kind!r} needs a run_id")
    if run_store is None:
        raise ExportError("no run store available")

    if kind == "bundle":
        economics = run_store.read_stage(run_id, stage="economics")
        if economics is None:
            raise ExportError(
                f"run {run_id} has no economics stage — run run_valuation first")
        return build_bundle_zip(
            economics, run_store.read_stage(run_id, stage="forecast"), run_id=run_id)

    stage = "economics" if kind == "volumes" else "forecast"
    payload = run_store.read_stage(run_id, stage=stage)
    if payload is None:
        raise ExportError(f"run {run_id} has no {stage} stage — nothing to export yet")
    return (build_volumes_csv(payload) if kind == "volumes"
            else build_parameters_csv(payload))
