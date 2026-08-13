"""Bulk DB access for the engine. One SQL query per call, regardless of N."""
import dataclasses

from utils.db import query as _query
from server.valuation.types import WellMeta


def _quote_apis(apis: list[str]) -> str:
    """SQL-quote a list of API strings for inclusion in an IN clause.

    Single-quote doubling is the Postgres standard. We also reject null bytes
    (Postgres rejects them with DataError anyway, but a clean ValueError is
    more useful) and empty strings (silent IN-match-nothing pollutes results)."""
    bad = [a for a in apis if not a or '\x00' in a]
    if bad:
        raise ValueError(f"invalid API string(s): {bad!r} (empty or contains null bytes)")
    return ", ".join("'" + a.replace("'", "''") + "'" for a in apis)


def bulk_load_wells(apis: list[str]) -> list[WellMeta]:
    """One query against public.wells + a derived COUNT against production. Returns
    a list of WellMeta, one per API actually present in the DB (missing APIs dropped).

    Raises:
        ValueError if any input API is empty or contains null bytes.
        psycopg.Error if the DB query fails (caller's responsibility to handle).
    """
    if not apis:
        return []
    quoted = _quote_apis(apis)
    sql = f"""
        WITH p AS (
            SELECT well_api, COUNT(*) AS n_months, MAX(prod_date) AS last_prod
            FROM public.production
            WHERE well_api IN ({quoted})
            GROUP BY well_api
        )
        SELECT
            w.well_api, w.well_name, w.well_status, w.basin, w.formation, w.county,
            w.lateral_length_ft, w.spud_date, w.completion_date, w.first_prod_date, w.operator,
            COALESCE(p.n_months, 0) AS n_history_months,
            p.last_prod AS last_prod_date,
            -- Always a POINT: geom is a POINT for permits/verticals but a
            -- LINESTRING survey for drilled horizontals, and WellMeta.geom_wkt
            -- promises a point (evidence's schematic map parses POINT only).
            -- Heel = first survey vertex; PointOnSurface backstops any other
            -- geometry type.
            ST_AsText(CASE
                WHEN GeometryType(w.geom) = 'POINT' THEN w.geom
                WHEN GeometryType(w.geom) = 'LINESTRING' THEN ST_StartPoint(w.geom)
                ELSE ST_PointOnSurface(w.geom)
            END) AS geom_wkt
        FROM public.wells w
        LEFT JOIN p ON p.well_api = w.well_api
        WHERE w.well_api IN ({quoted})
    """
    rows = _query(sql, schema="public", statement_timeout_ms=15_000)
    out: list[WellMeta] = []
    for r in rows:
        spud = r.get("spud_date")
        first_prod = r.get("first_prod_date")
        # planned_first_prod_date is NOT computed here — it depends on the
        # valuation as-of date (effective_date or today), which the loader
        # doesn't know. The orchestrator stamps it by well status; see
        # server.valuation.config.planned_first_prod_date.
        out.append(WellMeta(
            api=r["well_api"],
            status=r["well_status"],
            basin=r.get("basin"),
            formation=r.get("formation"),
            county=r.get("county"),
            lateral_ft=float(r["lateral_length_ft"]) if r.get("lateral_length_ft") else None,
            spud_date=spud,
            completion_date=r.get("completion_date"),
            first_prod_date=first_prod,
            last_prod_date=r.get("last_prod_date"),
            n_history_months=int(r["n_history_months"]),
            planned_first_prod_date=None,
            geom_wkt=r.get("geom_wkt"),
            operator=r.get("operator"),
            well_name=r.get("well_name"),
        ))
    return out


def apply_well_facts(metas: list[WellMeta], well_facts: dict) -> list[WellMeta]:
    """Fill-only application of user-supplied per-well physical facts.

    A supplied ``lateral_ft`` lands on a WellMeta ONLY when its DB-derived
    ``lateral_ft`` is missing (None). The DB value always wins when present, so
    well_facts is strictly a gap-filler for un-drilled permits whose lateral
    isn't on record yet. Wells not present in ``well_facts`` pass through
    untouched. Pure — no DB, no I/O.
    """
    if not well_facts:
        return metas
    out = []
    for m in metas:
        facts = well_facts.get(m.api)
        if facts and m.lateral_ft is None and facts.get("lateral_ft") is not None:
            out.append(dataclasses.replace(m, lateral_ft=float(facts["lateral_ft"])))
        else:
            out.append(m)
    return out


def bulk_load_production(apis: list[str]) -> dict[str, dict]:
    """Pull monthly production for the given APIs. One query, NO SUM/GROUP BY collapse.

    Returns: ``{api: {"months": list[str], "oil_bbl": list[float], "gas_mcf": list[float]}}``.
    ``months`` are ISO 8601 date strings (e.g. "2024-01-01"). Missing APIs return
    empty series under their key (never KeyError downstream).

    Raises:
        ValueError if any input API is empty or contains null bytes.
        psycopg.Error if the DB query fails (caller's responsibility to handle).
    """
    if not apis:
        return {}
    quoted = _quote_apis(apis)
    sql = f"""
        SELECT well_api, prod_date, oil_bbl, gas_mcf
        FROM public.production
        WHERE well_api IN ({quoted})
        ORDER BY well_api, prod_date
    """
    rows = _query(sql, schema="public", statement_timeout_ms=15_000)
    out: dict[str, dict] = {a: {"months": [], "oil_bbl": [], "gas_mcf": []} for a in set(apis)}
    for r in rows:
        d = out[r["well_api"]]
        d["months"].append(str(r["prod_date"]))
        d["oil_bbl"].append(float(r["oil_bbl"] or 0.0))
        d["gas_mcf"].append(float(r["gas_mcf"] or 0.0))
    return out
