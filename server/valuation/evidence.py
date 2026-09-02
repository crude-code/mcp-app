"""Evidence assembly: the judgment record behind a valuation, per assertion.

One evidence entry per `deal_forecast_wells` entry (a single well, a producing
cohort, or permits on a shared type curve). Every number here is hydrated
server-side from the run record and the DB — reported production history,
the committed curves evaluated forward from their anchors, per-well PV from
the persisted schedule, analog series and coordinates. Claude's judgment
(parameters, rationale, cohort selection) is displayed, never re-derived;
nothing in this module feeds the cashflow math.

Pure assembly — all DB loads are done by the caller (the orchestrator) and
passed in, mirroring `deal_sheet.py`.
"""
import math

import numpy as np

from server.valuation import config
from server.valuation.econ import npv
from server.valuation.forecast import curve_rate
from server.valuation.types import DeclineCurve, ForecastProvenance

# Display caps — evidence scales with the number of judgments, not wells, but
# these keep a pathological payload bounded.
_HIST_MONTHS_CAP = 60          # trailing history months shipped per entry
_FORECAST_MONTHS = 30          # curve months past the last reported month
_ANALOG_SERIES_MONTHS = 36     # analog / type-curve series length
_MEMBER_DETAIL_CAP = 25        # per-well rows per entry; the rest roll up

_MI_PER_DEG_LAT = 69.055
_MI_PER_DEG_LON = 69.172       # at the equator; scaled by cos(lat)


def _curve_from_dict(c: dict) -> DeclineCurve:
    """Serialized curve dict (forecast stage) → DeclineCurve for evaluation.
    Mirrors the orchestrator's tolerant deserialization (qi_peak fallback,
    None switch month → inf) without importing it — evidence is display-only."""
    switch = c.get("switch_month_from_peak")
    return DeclineCurve(
        qi=c["qi"] if "qi" in c else c["qi_peak"],
        di=c["di"], b=c["b"],
        terminal_di_monthly=c["terminal_di_monthly"],
        switch_month_from_peak=float("inf") if switch is None else switch,
        stream=c.get("stream", "oil"),
        provenance=ForecastProvenance(source="asserted", strategy=None),
    )


def _series(curve_dict: dict | None, n: int) -> np.ndarray:
    if not curve_dict or n <= 0:
        return np.zeros(max(n, 0))
    return np.asarray(curve_rate(_curve_from_dict(curve_dict), np.arange(n, dtype=float)))


def _months_between(a: str, b: str) -> int:
    """Whole months from month a to month b ('YYYY-MM'-ish strings)."""
    ay, am = int(a[:4]), int(a[5:7])
    by, bm = int(b[:4]), int(b[5:7])
    return (by - ay) * 12 + (bm - am)


def _parse_point_wkt(wkt: str | None) -> tuple[float, float] | None:
    """'POINT(lon lat)' → (lon, lat); None on anything else."""
    if not wkt or not wkt.upper().startswith("POINT"):
        return None
    try:
        inner = wkt[wkt.index("(") + 1:wkt.rindex(")")]
        lon_s, lat_s = inner.split()
        return float(lon_s), float(lat_s)
    except (ValueError, IndexError):
        return None


def _entry_groups(forecasts: dict) -> list[dict]:
    """Group the per-well forecast stage back into assertion entries.

    New stages carry `assertion.entry_id` (all member wells of one entry share
    it). Legacy fallbacks: cohort membership, else one group per well. Undrilled
    entries carrying an analog_cohort merge further by curve_label — several
    permits asserted individually on the same curve are one piece of evidence.
    """
    groups: dict[tuple, dict] = {}
    for api, fc in forecasts.items():
        assertion = fc.get("assertion")
        if assertion and assertion.get("entry_id"):
            key = ("entry", assertion["entry_id"])
        elif assertion and assertion.get("cohort"):
            key = ("cohort", tuple(sorted(assertion["cohort"].get("wells") or [api])))
        else:
            key = ("well", api)
        groups.setdefault(key, {"apis": [], "fc": fc, "assertion": assertion})
        groups[key]["apis"].append(api)

    # Merge same-curve_label analog entries (undrilled wells asserted one by one).
    merged: dict[tuple, dict] = {}
    for key, g in groups.items():
        ac = (g["assertion"] or {}).get("analog_cohort")
        label = ac.get("curve_label") if ac else None
        mkey = ("curve", label) if label else key
        if mkey in merged:
            merged[mkey]["apis"].extend(g["apis"])
        else:
            merged[mkey] = g
    return list(merged.values())


def _sum_history(apis: list[str], prod: dict) -> dict | None:
    """Calendar-aligned sum of member histories, capped to the trailing
    `_HIST_MONTHS_CAP` months. Column-oriented; months are 'YYYY-MM'."""
    by_month: dict[str, list[float]] = {}
    for api in apis:
        p = prod.get(api) or {}
        for m, o, g in zip(p.get("months") or [], p.get("oil_bbl") or [], p.get("gas_mcf") or []):
            key = str(m)[:7]
            cur = by_month.setdefault(key, [0.0, 0.0])
            cur[0] += o
            cur[1] += g
    if not by_month:
        return None
    months = sorted(by_month)[-_HIST_MONTHS_CAP:]
    return {
        "months": months,
        "oil": [round(by_month[m][0], 1) for m in months],
        "gas": [round(by_month[m][1], 1) for m in months],
    }


def _entry_curve(apis: list[str], forecasts: dict, anchor: str, last_hist: str | None) -> dict:
    """Committed curves summed across member wells, evaluated monthly from the
    anchor through `_FORECAST_MONTHS` past the last reported month (or from the
    anchor alone for undrilled entries). Member curves are the persisted
    (share- and uptime-scaled) curves, so the sum is exactly what economics
    projects."""
    overlap = 0
    if last_hist:
        overlap = max(0, _months_between(anchor, last_hist))
    n = min(overlap + 1 + _FORECAST_MONTHS, 120)
    oil = np.zeros(n)
    gas = np.zeros(n)
    for api in apis:
        fc = forecasts[api]
        oil += _series((fc.get("oil") or {}).get("curve"), n)
        gas += _series((fc.get("gas") or {}).get("curve"), n)
    return {
        "start_month": anchor[:7],
        "overlap_months": overlap + 1 if last_hist else 0,
        "oil": [round(float(v), 1) for v in oil],
        "gas": [round(float(v), 1) for v in gas],
    }


def _member_rows(apis: list[str], meta_by_api: dict, well_pv: dict) -> tuple[list[dict], dict | None, float | None]:
    """Per-well display rows (capped) + a roll-up of the remainder + entry PV."""
    rows = []
    for api in apis:
        m = meta_by_api.get(api)
        rows.append({
            "api": api,
            "name": (m.well_name if m and m.well_name else api),
            "operator": m.operator if m else None,
            "county": m.county if m else None,
            "formation": m.formation if m else None,
            "lateral_ft": m.lateral_ft if m else None,
            "status": m.status if m else None,
            "pv": well_pv.get(api),
        })
    rows.sort(key=lambda r: -(r["pv"] or 0.0))
    pvs = [r["pv"] for r in rows if r["pv"] is not None]
    entry_pv = round(float(sum(pvs))) if pvs else None
    more = None
    if len(rows) > _MEMBER_DETAIL_CAP:
        tail = rows[_MEMBER_DETAIL_CAP:]
        tail_pvs = [r["pv"] for r in tail if r["pv"] is not None]
        more = {"count": len(tail), "pv": round(float(sum(tail_pvs))) if tail_pvs else None}
        rows = rows[:_MEMBER_DETAIL_CAP]
    return rows, more, entry_pv


def _analog_first_prod(p: dict) -> str | None:
    months = p.get("months") or []
    return str(months[0])[:7] if months else None


def _analog_series(p: dict, lateral_ft: float | None, normalization: str) -> list[float] | None:
    """First `_ANALOG_SERIES_MONTHS` months on production, oil, normalized
    per 1,000' of lateral when asked and possible. None when it can't be
    honest (no history, or per-1000ft without a lateral on record)."""
    oil = p.get("oil_bbl") or []
    if not oil:
        return None
    vals = oil[:_ANALOG_SERIES_MONTHS]
    if normalization == "per_1000ft":
        if not lateral_ft:
            return None
        return [round(v * 1000.0 / lateral_ft, 1) for v in vals]
    return [round(float(v), 1) for v in vals]


def _local_miles(points: dict[str, tuple[float, float]]) -> tuple[dict[str, tuple[float, float]], float, float]:
    """lon/lat per api → local mile-space coords with a 0.5 mi pad, plus the
    bounding width/height. Flat-earth is exact enough at type-curve radii."""
    lats = [ll[1] for ll in points.values()]
    lons = [ll[0] for ll in points.values()]
    lat_mid = sum(lats) / len(lats)
    kx = _MI_PER_DEG_LON * math.cos(math.radians(lat_mid))
    lon0, lat0 = min(lons), min(lats)
    out = {
        api: (round((lon - lon0) * kx + 0.5, 2), round((lat - lat0) * _MI_PER_DEG_LAT + 0.5, 2))
        for api, (lon, lat) in points.items()
    }
    w = max(x for x, _ in out.values()) + 0.5
    h = max(y for _, y in out.values()) + 0.5
    return out, round(max(w, 1.0), 2), round(max(h, 1.0), 2)


def _type_curve_block(*, apis: list[str], forecasts: dict, ac: dict,
                      meta_by_api: dict, analog_meta: dict, analog_prod: dict) -> dict:
    """The analog-cohort evidence behind one type curve: the normalized curve
    series, kept analogs with their real series, excluded analogs with the
    reason, and a schematic mile-space map when coordinates exist."""
    normalization = ac.get("normalization", "per_1000ft")

    # The curve, normalized off the first subject's committed oil curve. The
    # committed qi is absolute for that subject; per-1000ft display divides its
    # lateral back out.
    first = apis[0]
    subj_meta = meta_by_api.get(first)
    raw = _series((forecasts[first].get("oil") or {}).get("curve"), _ANALOG_SERIES_MONTHS)
    if normalization == "per_1000ft" and subj_meta and subj_meta.lateral_ft:
        curve_series = [round(float(v) * 1000.0 / subj_meta.lateral_ft, 1) for v in raw]
    else:
        normalization = "absolute"
        curve_series = [round(float(v), 1) for v in raw]

    laterals = [meta_by_api[a].lateral_ft for a in apis
                if meta_by_api.get(a) and meta_by_api[a].lateral_ft]
    plan_lat = round(sum(laterals) / len(laterals)) if laterals else None

    kept = []
    for a in ac.get("kept") or []:
        m = analog_meta.get(a)
        p = analog_prod.get(a) or {}
        kept.append({
            "api": a,
            "name": (m.well_name if m and m.well_name else a),
            "operator": m.operator if m else None,
            "formation": m.formation if m else None,
            "lateral_ft": m.lateral_ft if m else None,
            "first_prod": _analog_first_prod(p),
            "cum12_oil": round(sum((p.get("oil_bbl") or [])[:12])) if p.get("oil_bbl") else None,
            "series": _analog_series(p, m.lateral_ft if m else None, normalization),
        })
    excluded = []
    for e in ac.get("excluded") or []:
        m = analog_meta.get(e["api"])
        excluded.append({
            "api": e["api"],
            "name": (m.well_name if m and m.well_name else e["api"]),
            "operator": m.operator if m else None,
            "formation": m.formation if m else None,
            "lateral_ft": m.lateral_ft if m else None,
            "reason": e["reason"],
        })

    # Schematic map: subjects + analogs in local mile-space. Wells without a
    # point on record simply don't appear; no points at all → no map.
    lonlat: dict[str, tuple[float, float]] = {}
    for a in apis:
        ll = _parse_point_wkt(meta_by_api[a].geom_wkt if meta_by_api.get(a) else None)
        if ll:
            lonlat[a] = ll
    for a in list(analog_meta):
        ll = _parse_point_wkt(analog_meta[a].geom_wkt)
        if ll:
            lonlat[a] = ll
    map_block = None
    if lonlat:
        coords, w_mi, h_mi = _local_miles(lonlat)
        for row in kept + excluded:
            xy = coords.get(row["api"])
            row["x"], row["y"] = xy if xy else (None, None)
        map_block = {
            "w_mi": w_mi, "h_mi": h_mi,
            "subjects": [
                {
                    "api": a,
                    "name": (meta_by_api[a].well_name if meta_by_api.get(a) and meta_by_api[a].well_name else a),
                    "lateral_ft": meta_by_api[a].lateral_ft if meta_by_api.get(a) else None,
                    "x": coords[a][0], "y": coords[a][1],
                }
                for a in apis if a in coords
            ],
        }

    return {
        "criteria": ac.get("criteria"),
        "normalization": normalization,
        "series": curve_series,
        "plan_lat_ft": plan_lat,
        "kept": kept,
        "excluded": excluded,
        "map": map_block,
    }


def _assertion_display(assertion: dict | None) -> dict | None:
    if not assertion:
        return None
    return {
        "oil": (assertion.get("asserted") or {}).get("oil"),
        "gas": (assertion.get("asserted") or {}).get("gas"),
        "uptime_factor": assertion.get("uptime_factor"),
        "struck_months": assertion.get("struck_months") or [],
        "rationale": assertion.get("rationale"),
    }


def build_evidence(*, forecast: dict, schedule: dict, meta_by_api: dict,
                   prod: dict, analog_meta: dict, analog_prod: dict,
                   rate_centers: dict) -> dict:
    """The evidence stage: `{"entries": [...]}`, one entry per assertion,
    sorted by PV descending.

    `forecast` is the run's forecast stage; `schedule` the serialized economics
    schedule (its `by_well` net cashflows price the entries — PV is None for
    the rare >200-well run where the audit columns were omitted); `prod` /
    `analog_prod` are `bulk_load_production` maps; `meta_by_api` /
    `analog_meta` are WellMeta maps. Per-well PV discounts at the well's
    status-center rate on the base deck, so entry PVs sum to the headline
    `npv_at_centers.total` by construction.
    """
    forecasts = forecast.get("forecasts") or {}
    by_well = schedule.get("by_well") or {}

    well_pv: dict[str, float | None] = {}
    for api, fc in forecasts.items():
        cols = by_well.get(api)
        if not cols:
            well_pv[api] = None
            continue
        rate = rate_centers.get(config.status_code(fc.get("status")), 0.15)
        well_pv[api] = round(float(npv(np.asarray(cols["net_cashflow"], dtype=float),
                                       annual_rate=float(rate))))

    entries = []
    for g in _entry_groups(forecasts):
        apis = g["apis"]
        assertion = g["assertion"]
        fc0 = forecasts[apis[0]]
        anchor = fc0.get("anchor_month")
        producing = any((prod.get(a) or {}).get("months") for a in apis)

        rows, more, entry_pv = _member_rows(apis, meta_by_api, well_pv)
        ac = (assertion or {}).get("analog_cohort")

        if len(apis) == 1:
            label = rows[0]["name"]
        elif ac:
            label = ac.get("curve_label")
        else:
            ops = [r["operator"] for r in rows if r["operator"]]
            label = f"{len(apis)} wells" + (f" · {ops[0].title()}" if ops else "")

        entry: dict = {
            "id": (assertion or {}).get("entry_id") or apis[0],
            "kind": "producing" if producing else "undrilled",
            "label": label,
            "pv": entry_pv,
            "anchor_month": anchor,
            "wells": rows,
            "wells_more": more,
            "assertion": _assertion_display(assertion),
        }

        if producing:
            hist = _sum_history(apis, prod)
            entry["hist"] = hist
            last_hist = hist["months"][-1] if hist else None
            if anchor:
                entry["curve"] = _entry_curve(apis, forecasts, anchor, last_hist)
        else:
            entry["online_month"] = anchor
            if anchor:
                entry["curve"] = _entry_curve(apis, forecasts, anchor, None)
            if ac:
                entry["type_curve"] = _type_curve_block(
                    apis=apis, forecasts=forecasts, ac=ac,
                    meta_by_api=meta_by_api, analog_meta=analog_meta,
                    analog_prod=analog_prod,
                )
        entries.append(entry)

    entries.sort(key=lambda e: -(e["pv"] or 0.0))
    total = sum(e["pv"] for e in entries if e["pv"] is not None)
    for e in entries:
        e["pv_share"] = round(e["pv"] / total, 4) if (e["pv"] is not None and total) else None
    return {"entries": entries}


def collect_analog_apis(forecast: dict) -> tuple[list[str], list[str]]:
    """(kept, all) analog APIs referenced by the run's assertions — the loads
    the orchestrator must do before calling `build_evidence`. Kept analogs
    need production; excluded ones only meta."""
    kept: set[str] = set()
    all_: set[str] = set()
    for fc in (forecast.get("forecasts") or {}).values():
        ac = (fc.get("assertion") or {}).get("analog_cohort")
        if not ac:
            continue
        kept.update(ac.get("kept") or [])
        all_.update(ac.get("kept") or [])
        all_.update(e["api"] for e in (ac.get("excluded") or []))
    return sorted(kept), sorted(all_)
