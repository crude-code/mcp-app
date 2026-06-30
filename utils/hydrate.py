"""Per-widget hydration for briefing specs.

One dispatch table for every briefing widget type. Per-widget failure is
isolated: log + attach `_error` + an empty payload; never fail the whole spec.

**Round-trip contract:** hydration is *additive*. Input fields (`query`,
`value_template`) are preserved on the returned widget, with output payloads
added on non-conflicting keys.
"""
import logging
import math

from utils.futures_callouts import (
    FUTURES_CODES,
    build_futures_callout_fields,
    fetch_front_month_rows,
)
from utils.spot_callouts import CODE_COLUMNS, build_callout_fields, fetch_spot_rows
from utils.sql_guard import GuardError, dry_run, run_guarded

log = logging.getLogger("ei.hydrate")


def _run(sql: str) -> list[dict]:
    # Caps default to sql_guard.DEFAULT_* (200 rows / 50KB / 5s).
    return run_guarded(sql, schema="public")["rows"]


# ── Per-widget hydrators ────────────────────────────────────────────────────

def _hydrate_callout(w: dict) -> dict:
    out = {**w}
    code = w.get("code")
    if code in CODE_COLUMNS:
        rows = fetch_spot_rows()
        fields = build_callout_fields(rows, CODE_COLUMNS[code])
        if fields:
            out.update(fields)
        return out

    if code in FUTURES_CODES:
        rows = fetch_front_month_rows()
        fields = build_futures_callout_fields(rows, FUTURES_CODES[code])
        if fields:
            out.update(fields)
        return out

    if w.get("query"):
        try:
            rows = _run(w["query"])
            if rows:
                row = rows[0]
                template = w.get("value_template")
                if template:
                    try:
                        out["value"] = template.format(**row)
                    except (KeyError, IndexError) as e:
                        out["_error"] = f"value_template miss: {e}"
                        out["value"] = str(next(iter(row.values())))
                else:
                    out["value"] = str(next(iter(row.values())))
        except Exception as e:
            log.warning("callout query failed (%s): %s", w.get("label"), e)
            out["_error"] = str(e)
            out["value"] = ""
    return out


def _hydrate_chart(w: dict) -> dict:
    out = {**w}
    try:
        out["data"] = _run(w["query"])
    except Exception as e:
        log.warning("%s query failed (%s): %s", w["type"], w.get("label"), e)
        out["data"] = []
        out["_error"] = str(e)
    return out


def _hydrate_table(w: dict) -> dict:
    out = {**w}
    try:
        out["rows"] = _run(w["query"])
    except Exception as e:
        log.warning("table query failed (%s): %s", w.get("label"), e)
        out["rows"] = []
        out["_error"] = str(e)
    return out


# ── Dispatch + spec walker ──────────────────────────────────────────────────

_DISPATCH = {
    "callout": _hydrate_callout,
    "line_chart": _hydrate_chart,
    "bar_chart": _hydrate_chart,
    "table": _hydrate_table,
}


def _hydrate_one(widget: dict) -> dict:
    handler = _DISPATCH.get(widget.get("type"))
    return handler(widget) if handler else {**widget}


def _scrub_nonfinite(obj):
    """Recursively replace NaN / ±Infinity floats with None.

    JSON (RFC 8259) does not allow ``NaN`` or ``Infinity`` as numeric
    literals. Python's ``json.dumps`` emits them by default — and
    ``json.loads`` accepts them symmetrically — so a Python ↔ Python
    round-trip works, but JavaScript's strict ``JSON.parse`` chokes on
    the bare ``NaN`` token. The renderer and the MCP host both use
    ``JSON.parse`` to read tool results, so any non-finite float in a
    spec breaks the surface.

    Postgres can return NaN (e.g., a missing tenor on a futures curve);
    psycopg surfaces it as ``float('nan')``. This walker normalizes them
    to ``None`` (JSON ``null``), which Recharts and the other renderer
    components already handle as "missing value."
    """
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _scrub_nonfinite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_nonfinite(x) for x in obj]
    return obj


def hydrate_spec(spec: dict) -> dict:
    """Return a new spec with widget data filled in.

    Walks `spec.sections[].widgets[]` and runs each through the dispatch
    table. Per-widget failures are isolated (logged + `_error` field on
    the widget) so a single bad query never blanks the whole spec.

    Used by both `data_analyst` specs and the Portal dashboard. The
    spec shape is the same on both surfaces; only the widget vocabulary
    differs in practice, but the dispatch table covers every type either
    surface supports.

    Specs without a ``sections`` key (e.g. ``kind="error"`` briefings) are
    returned unchanged so we don't silently add an empty sections field.

    NaN / ±Inf floats are scrubbed to ``None`` before return so the spec
    round-trips through ``json.dumps`` → JS ``JSON.parse`` without crashing.
    """
    if "sections" not in spec:
        return _scrub_nonfinite(spec)
    sections_out = []
    for section in spec["sections"]:
        widgets_out = [_hydrate_one(w) for w in section.get("widgets", [])]
        sections_out.append({**section, "widgets": widgets_out})
    return _scrub_nonfinite({**spec, "sections": sections_out})


def validate_widget_queries(spec: dict) -> list[dict]:
    """Dry-run every widget query in a spec.

    Called by the persist endpoints as a hook between spec validation
    and token consumption — if any query fails to parse or plan, the
    endpoint returns 422 with the error list and the agent can retry
    with a fixed spec. Empty list means every query is safe to hydrate.

    Only widgets with a non-empty string ``query`` field are checked.
    Code-based callouts, commentary, and other query-less widgets are
    skipped.
    """
    errors: list[dict] = []

    def _walk(widgets: list[dict], si: int) -> None:
        for wi, widget in enumerate(widgets):
            sql = widget.get("query")
            if not isinstance(sql, str) or not sql.strip():
                continue
            try:
                dry_run(sql)
            except GuardError as e:
                errors.append({
                    "section_index": si,
                    "widget_index": wi,
                    "type": widget.get("type"),
                    "label": widget.get("label"),
                    "error": str(e),
                })

    for si, section in enumerate(spec.get("sections", [])):
        _walk(section.get("widgets", []), si)
    return errors
