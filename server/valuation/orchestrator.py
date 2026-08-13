"""Valuation orchestrator. Runs forecast_wells → economics → deal-sheet assembly.

The forecast side is accept-and-echo: Claude asserts decline parameters
({qi, di, b} per stream, an anchor month, optional uptime factor) per well or
cohort; the server bounds-validates, persists, and echoes the consequences
(``server.valuation.consequences``). Nothing here ever chooses a parameter —
the decision doctrine lives in the ``well-forecasting`` skill, and the
benchmark evidence for this division of labor lives in the sibling
``forecast-benchmark`` repo.
"""
import math
import uuid
from datetime import date, datetime, timezone

import numpy as np
from dateutil.relativedelta import relativedelta

from server.valuation import config
from server.valuation import consequences as cq
from server.valuation import strip
from server.valuation.casefile import MAX_ASSET_WELLS, parse_run_params
from server.valuation.econ import cashflow_components, compute_gross_revenue, npv, resolve_well_interest
from server.valuation.evidence import build_evidence, collect_analog_apis
from server.valuation.forecast import make_curve, make_zero_curve, project
from server.valuation.run_record import ValuationRunStore
from server.valuation.types import DeclineCurve, Forecast, ForecastProvenance, WellMeta
from server.valuation.wells import bulk_load_production, bulk_load_wells


class ForecastValidationError(Exception):
    """Bounce: the forecast_wells call had validation violations. Carries every
    violation in the call (never fail-fast) as ``[{entry, well?, field, message}]``.
    Nothing is persisted on a bounce."""
    def __init__(self, violations: list[dict]):
        self.violations = violations
        super().__init__("validation_failed")


# Asserted-parameter sanity bounds. These are bounds, not judgment — anything
# inside them is Claude's call; the echo is where a bad-but-legal number gets
# caught. b's upper bound follows the old plan-validation precedent (2.0).
_QI_MIN = 0.0                    # exclusive
_DI_RANGE = (0.0, 1.0)           # exclusive both ends, nominal monthly
_B_RANGE = (0.0, 2.0)            # inclusive both ends
_UPTIME_RANGE = (0.5, 1.0)       # inclusive both ends
_MAX_FUTURE_ANCHOR_MONTHS = 360  # loose cap on asserted online dates

_STREAMS = ("oil", "gas")
_PARAM_FIELDS = {"qi", "di", "b"}
_PROD_COL = {"oil": "oil_bbl", "gas": "gas_mcf"}

# analog_cohort: the structured record of the analog method's cohort judgment.
# Display evidence only — nothing here feeds the cashflow math.
_MAX_ANALOGS = 40                      # per list (kept / excluded)
_COHORT_KEYS_REQ = {"curve_label", "criteria", "kept"}
_COHORT_KEYS_ALL = _COHORT_KEYS_REQ | {"normalization", "excluded"}
_NORMALIZATIONS = ("per_1000ft", "absolute")


def _resolve_asset_list(asset_list: dict) -> list[str]:
    if asset_list.get("well_apis"):
        apis = list(dict.fromkeys(asset_list["well_apis"]))
        if len(apis) > MAX_ASSET_WELLS:
            raise ValueError(
                f"asset_list has {len(apis)} wells; at most {MAX_ASSET_WELLS} per valuation"
            )
        return apis

    # filter_sql is agent-authored — route through the SELECT-only guard.
    if not asset_list.get("filter_sql"):
        raise ValueError("asset_list must carry well_apis or filter_sql")
    where = asset_list["filter_sql"].strip()
    if not where.lower().startswith("where"):
        where = "WHERE " + where
    sql = f"SELECT well_api FROM public.wells {where}"

    from utils.sql_guard import GuardError, run_guarded
    from utils.schemas import EXPLORATION_SCHEMAS
    try:
        result = run_guarded(
            sql,
            schema="public",
            allowed_schemas=EXPLORATION_SCHEMAS,
            row_cap=MAX_ASSET_WELLS,
            size_cap_bytes=500_000,
        )
    except GuardError as exc:
        if "row cap" in str(exc):
            raise ValueError(
                f"filter_sql matched more than {MAX_ASSET_WELLS} wells — tighten the filter"
            ) from exc
        raise
    return [r["well_api"] for r in result["rows"]]


def _validate_by_api_membership(by_api: dict | None, known_apis: set[str]) -> None:
    """Every interest.by_api key must reference a well in the asset list.

    resolve_well_interest silently falls back to blanket interest for any well
    not in by_api — so a typo'd by_api key would silently misprice the well it
    was meant to override. Bounce it loudly instead."""
    if not by_api:
        return
    unknown = [api for api in by_api if api not in known_apis]
    if unknown:
        shown = ", ".join(unknown[:5])
        raise ValueError(
            f"{len(unknown)} interest.by_api key(s) are not in the asset list: "
            f"{shown}{'...' if len(unknown) > 5 else ''} — a typo here would "
            "silently misprice those wells"
        )


def _serialize_curve(c: DeclineCurve) -> dict:
    """DeclineCurve → JSON-safe dict. Infinity switch month persists as None.
    Provenance: only source + strategy are persisted; other fields are dropped."""
    switch = c.switch_month_from_peak
    return {
        "qi": c.qi, "di": c.di, "b": c.b,
        "terminal_di_monthly": c.terminal_di_monthly,
        "switch_month_from_peak": switch if math.isfinite(switch) else None,
        "stream": c.stream,
        "provenance": {"source": c.provenance.source, "strategy": c.provenance.strategy},
    }


def _deserialize_curve(c: dict) -> DeclineCurve:
    """Inverse of _serialize_curve. None switch month → float('inf').
    Tolerant on two axes so durable pre-assertion runs still replay: the qi key
    (fit-era stages persisted ``qi_peak``; that qi was a peak rate, which the
    stage's per-stream ``peak_month`` re-anchors at load) and provenance
    (synthesized when absent)."""
    switch = c["switch_month_from_peak"]
    if switch is None:
        switch = float("inf")
    prov = c.get("provenance") or {}
    return DeclineCurve(
        qi=c["qi"] if "qi" in c else c["qi_peak"],
        di=c["di"], b=c["b"],
        terminal_di_monthly=c["terminal_di_monthly"],
        switch_month_from_peak=switch,
        stream=c["stream"],
        provenance=ForecastProvenance(
            source=prov.get("source", "cohort"),
            strategy=prov.get("strategy"),
        ),
    )


def _place_curve(*, self_curve: dict, start_date: str, strategy: str,
                 peak_date: str | None = None) -> dict:
    """Build a serialized-forecast dict from a (dateless) serialized curve and a
    start date. The forecast tools store dateless curves; run_valuation supplies
    start_date (PDP: the well's historical anchor; PUD: the status-derived online
    date). peak_date defaults to start_date (PUDs/climbing: peak is at the anchor).
    For producing wells with history, pass the historical peak month so project()
    sees a non-zero peak_offset and continues the decline instead of restarting."""
    return {
        "curve": self_curve,
        "peak_date": peak_date or start_date,
        "start_date": start_date,
        "strategy": strategy,
    }


def _deserialize_forecast(d: dict) -> Forecast:
    """Inverse of _serialize_forecast. Handles `None` switch_month as `float('inf')`.
    provenance is read from the curve dict when present (old serialized path) or
    synthesized when absent (new dateless-curve path from forecast_wells stages)."""
    curve_prov = (d["curve"].get("provenance") or {})
    return Forecast(
        curve=_deserialize_curve(d["curve"]),
        peak_date=date.fromisoformat(d["peak_date"]),
        start_date=date.fromisoformat(d["start_date"]),
        provenance=ForecastProvenance(
            source=curve_prov.get("source", "cohort"),
            strategy=d.get("strategy"),
        ),
    )


_SCHEDULE_COLS = (
    "oil_bbl", "gas_mcf", "net_oil", "net_gas", "gross_rev", "net_rev",
    "sev_tax", "gpt", "capex", "opex", "net_cashflow",
)


def _build_schedule(
    *,
    forecasts: dict,
    needs_capex: dict,
    origin: date,
    horizon: int,
    oil_price: float,
    gas_price: float,
    oil_diff: float,
    gas_diff: float,
    gas_btu_factor: float = config.ECON.gas_btu_factor,
    interest_type: str,
    wi_pct: float | None,
    nri_pct: float | None,
    decimal: float | None,
    tax_pct: float,
    gpt_pct: float,
    capex_per_well: float,
    opex_per_well_month: float,
    opex_per_bbl: float,
    by_api: dict | None = None,
) -> dict:
    """Per-well + total monthly cashflow schedule on the calendar axis.

    Each well is projected at its calendar offset from ``origin`` (PDP at month
    0, DUC/PUD at their online month), priced, costed (WI only — the AFE lands at
    a non-producing well's online month, opex accrues while it flows), and run
    through ``cashflow_components``. Totals are the elementwise sum across wells,
    so ``NPV(totals)`` equals the sum of the per-well NPVs by construction — the
    persisted schedule reconciles to the headline exactly.

    Returns ``{"by_well": {api: {col: ndarray}}, "totals": {col: ndarray}}`` with
    the columns in ``_SCHEDULE_COLS``.
    """
    month_index = np.arange(horizon, dtype=float)
    by_well: dict[str, dict[str, np.ndarray]] = {}
    for api, fs in forecasts.items():
        f_oil = _deserialize_forecast(fs["oil"])
        f_gas = _deserialize_forecast(fs["gas"])
        start = f_oil.start_date.replace(day=1)
        offset = max(0, (start.year - origin.year) * 12 + (start.month - origin.month))

        oil = np.zeros(horizon)
        gas = np.zeros(horizon)
        if offset < horizon:
            _, oil_rates = project(f_oil, horizon_months=horizon - offset)
            _, gas_rates = project(f_gas, horizon_months=horizon - offset)
            oil[offset:] = oil_rates
            gas[offset:] = gas_rates

        # Per-well interest: a by_api entry overrides the blanket scalars.
        eff = resolve_well_interest(
            interest_type, api, wi_pct=wi_pct, nri_pct=nri_pct, decimal=decimal, by_api=by_api,
        )
        w_wi, w_nri, w_dec = eff.get("wi_pct"), eff.get("nri_pct"), eff.get("decimal")

        gross = compute_gross_revenue(
            oil, gas, oil_price=oil_price, gas_price=gas_price,
            oil_diff=oil_diff, gas_diff=gas_diff, gas_btu_factor=gas_btu_factor,
        )
        capex = np.zeros(horizon)
        opex = np.zeros(horizon)
        if interest_type == "wi":
            online = (month_index >= offset).astype(float)
            opex = w_wi * (opex_per_well_month * online + opex_per_bbl * oil)
            if needs_capex.get(api) and offset < horizon:
                capex[offset] = w_wi * capex_per_well     # drilling AFE at the online month

        comp = cashflow_components(
            gross_rev=gross, interest_type=interest_type,
            capex_per_month=capex, opex_per_month=opex,
            tax_pct=tax_pct, gpt_pct=gpt_pct,
            wi_pct=w_wi, nri_pct=w_nri, decimal=w_dec,
        )
        # Net volumes scale gross by this well's revenue interest (nri for WI,
        # decimal for minerals) — so the production chart can sum true net volumes
        # even when interest varies well to well.
        net_frac = w_nri if interest_type == "wi" else w_dec
        by_well[api] = {
            "oil_bbl": oil, "gas_mcf": gas,
            "net_oil": oil * net_frac, "net_gas": gas * net_frac,
            **comp,
        }

    totals = {col: np.zeros(horizon) for col in _SCHEDULE_COLS}
    for sched in by_well.values():
        for col in _SCHEDULE_COLS:
            totals[col] += sched[col]
    return {"by_well": by_well, "totals": totals}


def _partition_net_cashflow(by_well: dict, statuses: dict) -> dict[str, np.ndarray]:
    """Sum per-well net cashflow into the three deal-sheet status buckets.

    Returns ``{code: ndarray}`` for every code in ``config.ECON.default_rate_centers``
    (zeros when no well maps to that bucket). Bucketing is by ``public.wells.well_status``
    via :func:`config.status_code`; a well missing from ``statuses`` falls back to
    the producing bucket. Because cashflows add, the three buckets sum exactly to
    ``schedule["totals"]["net_cashflow"]``.
    """
    horizon = len(next(iter(by_well.values()))["net_cashflow"]) if by_well else 0
    buckets = {code: np.zeros(horizon) for code in config.ECON.default_rate_centers}
    for api, cols in by_well.items():
        code = config.status_code(statuses.get(api))
        buckets[code] = buckets[code] + cols["net_cashflow"]
    return buckets


def _rate_label(rate: float) -> str:
    """Decimal annual rate → the cube's percent-string key (0.175 → '17.5')."""
    return f"{rate * 100:g}"


def _status_pv_cube(schedules_by_deck: dict[str, dict], statuses: dict, rate_centers: dict) -> dict:
    """The risked-PV cube: ``deck → status code → rate label → NPV (USD)``.

    Each status's three rungs are ``config.rate_ladder(rate_centers[code])`` —
    the per-status center banded ±spread. Status PVs are additive at a common
    rate, so the client sums the three selected cells for the headline.
    """
    cube: dict[str, dict] = {}
    for deck_label, sched in schedules_by_deck.items():
        buckets = _partition_net_cashflow(sched["by_well"], statuses)
        cube[deck_label] = {
            code: {_rate_label(r): npv(buckets[code], annual_rate=r)
                   for r in config.rate_ladder(center)}
            for code, center in rate_centers.items()
        }
    return cube


def _compute_npv_by_status(*, base_schedule_kwargs: dict, oil_price_vec, gas_price_vec,
                           price_mode: str, statuses: dict, rate_centers: dict) -> dict:
    """Build a cashflow schedule per deck and return the risked-PV cube.

    The first deck (``base``) prices off ``oil_price_vec`` — the run's actual oil
    path (the strip, or a flat override as a constant vector). The remaining
    decks are flat-oil reference scenarios from ``config.ECON.deck_oil_flat``
    (constant ``$/bbl`` vectors). Gas is held at ``gas_price_vec`` across every
    deck. ``base_schedule_kwargs`` are the :func:`_build_schedule` arguments
    minus ``oil_price``/``gas_price``. Volumes are price-independent, so only the
    oil price varies across decks — costs (capex/opex) are unchanged.
    """
    labels, base = config.deck_labels(price_mode)
    horizon = len(oil_price_vec)
    schedules = {
        base: _build_schedule(**base_schedule_kwargs,
                              oil_price=oil_price_vec, gas_price=gas_price_vec)
    }
    for price, label in zip(config.ECON.deck_oil_flat, labels[1:]):
        schedules[label] = _build_schedule(**base_schedule_kwargs,
                                           oil_price=np.full(horizon, price), gas_price=gas_price_vec)
    return _status_pv_cube(schedules, statuses, rate_centers)


_MAX_BY_WELL_AUDIT = 200  # per-well audit rows omitted above this count to keep JSONB manageable


def _serialize_schedule(sched: dict, *, origin: date, horizon: int, rate_centers: dict) -> dict:
    """JSON-safe, rounded form of a schedule for the run record (the audit trail).

    Column-oriented (parallel arrays index-aligned to ``months``) and rounded to
    cents to keep the JSONB compact.

    ``by_well`` is included only when the deal has ≤ ``_MAX_BY_WELL_AUDIT`` wells;
    for larger deals it is omitted (``by_well_omitted`` records why) to avoid
    generating hundreds of MB of JSONB. Totals are always built."""
    months: list[str] = []
    cur = origin
    for _ in range(horizon):
        months.append(cur.isoformat())
        cur = cur + relativedelta(months=1)

    def _cols(d: dict) -> dict:
        return {col: [round(float(v), 2) for v in d[col]] for col in _SCHEDULE_COLS}

    result: dict = {
        "origin": origin.isoformat(),
        "months": months,
        "rate_centers": dict(rate_centers),
        "columns": list(_SCHEDULE_COLS),
        "totals": _cols(sched["totals"]),
    }
    n_wells = len(sched["by_well"])
    if n_wells <= _MAX_BY_WELL_AUDIT:
        result["by_well"] = {api: _cols(cols) for api, cols in sched["by_well"].items()}
    else:
        result["by_well_omitted"] = (
            f"{n_wells} wells exceeds the {_MAX_BY_WELL_AUDIT}-well audit cap"
        )
    return result


def _interest_from_record(case_file: dict | None, assumptions: dict) -> dict:
    """Normalized interest inputs, sourced from the authoritative case file.

    Returns ``{interest_type, wi_pct, nri_pct}`` (WI) or ``{interest_type,
    decimal}`` (minerals), plus an optional ``by_api`` map of per-well overrides.
    The case file is the source of truth (validated at the MCP boundary); for
    legacy runs whose case file predates server-sourced interest, falls back to
    the agent's ``assumptions`` for the blanket numbers.
    """
    case_interest = (case_file or {}).get("interest")
    src = case_interest if isinstance(case_interest, dict) else assumptions
    itype = (case_file or {}).get("interest_type") or assumptions.get("interest_type")

    out: dict = {"interest_type": itype}
    if itype == "wi":
        out["wi_pct"] = float(src["wi_pct"])
        out["nri_pct"] = float(src["nri_pct"])
    else:
        out["decimal"] = float(src["decimal"])

    by_api = case_interest.get("by_api") if isinstance(case_interest, dict) else None
    if by_api:
        out["by_api"] = by_api
    return out


def _economics_from_forecasts(*, forecasts: dict, needs_capex: dict,
                              statuses: dict, econ_overrides: dict) -> dict:
    """Pure economics: monthly schedule → risked-PV cube → NPV. Takes the
    assembled (already calendar-placed) forecasts + per-well capex flags +
    statuses. Every economic number is read from econ_overrides (the
    validated params)."""
    inputs = config.resolve_price_inputs(econ_overrides)
    horizon = inputs["horizon_months"]
    origin = config.first_of_next_month(
        config.resolve_as_of(econ_overrides.get("effective_date"), today=date.today())
    )
    # Base oil/gas price PATHS over the horizon: live NYMEX strip by default
    # (flat is an opt-in override). compute_gross_revenue broadcasts a vector
    # price against the per-month production vector — no formula change.
    price = strip.resolve_price_series(
        econ_overrides, origin=origin, horizon_months=horizon,
        flat_oil=inputs["oil_price"], flat_gas=inputs["gas_price"],
    )
    oil_vec, gas_vec = price["oil"], price["gas"]
    # inputs carries representative display scalars + the mode/trade-date for the
    # econ panel; the schedule/cube use the full vectors above.
    inputs["oil_price"] = price["oil_repr"]
    inputs["gas_price"] = price["gas_repr"]
    inputs["price_mode"] = price["mode"]
    inputs["strip_trade_date"] = price["trade_date"].isoformat() if price["trade_date"] else None

    interest = _interest_from_record({"interest_type": econ_overrides.get("interest_type"),
                                      "interest": econ_overrides.get("interest")}, {})
    interest_type = interest["interest_type"]
    _validate_by_api_membership(interest.get("by_api"), set(forecasts))

    base_schedule_kwargs = dict(
        forecasts=forecasts, needs_capex=needs_capex, origin=origin,
        horizon=horizon, oil_diff=inputs["oil_diff"], gas_diff=inputs["gas_diff"],
        gas_btu_factor=inputs["gas_btu_factor"],
        interest_type=interest_type, wi_pct=interest.get("wi_pct"),
        nri_pct=interest.get("nri_pct"), decimal=interest.get("decimal"),
        by_api=interest.get("by_api"), tax_pct=inputs["tax_pct"], gpt_pct=inputs["gpt_pct"],
        capex_per_well=float(econ_overrides.get("capex_per_well_usd", config.ECON.capex_per_well_usd)),
        opex_per_well_month=float(econ_overrides.get("opex_per_well_per_month_usd", config.ECON.opex_per_well_per_month_usd)),
        opex_per_bbl=float(econ_overrides.get("opex_per_bbl_usd", config.ECON.opex_per_bbl_usd)),
    )
    sched = _build_schedule(**base_schedule_kwargs, oil_price=oil_vec, gas_price=gas_vec)
    rate_centers = config.resolve_rate_centers(econ_overrides)
    net_cf = sched["totals"]["net_cashflow"]
    npv_by_status = _compute_npv_by_status(
        base_schedule_kwargs=base_schedule_kwargs, oil_price_vec=oil_vec,
        gas_price_vec=gas_vec, price_mode=price["mode"],
        statuses=statuses, rate_centers=rate_centers,
    )
    deck = config.default_deck_label(price["mode"])
    by_status_center = {
        code: float(npv_by_status[deck][code][_rate_label(config.rate_ladder(center)[1])])
        for code, center in rate_centers.items()
    }
    npv_at_centers = {"by_status": by_status_center, "total": float(sum(by_status_center.values()))}
    return {
        "npv_at_centers": npv_at_centers, "rate_centers": rate_centers,
        "npv_by_status": npv_by_status, "cashflow_total_undiscounted": float(net_cf.sum()),
        "horizon_months": horizon, "inputs": inputs, "interest": interest,
        "schedule": _serialize_schedule(sched, origin=origin, horizon=horizon, rate_centers=rate_centers),
        "price_path": {
            "oil": [round(float(v), 4) for v in oil_vec],
            "gas": [round(float(v), 4) for v in gas_vec],
        },
        "cost_inputs": {
            "capex_per_well": float(base_schedule_kwargs["capex_per_well"]),
            "opex_per_well_month": float(base_schedule_kwargs["opex_per_well_month"]),
            "opex_per_bbl": float(base_schedule_kwargs["opex_per_bbl"]),
        },
    }


def compose_artifact_payload_for_run(run_id: str) -> dict:
    """Read the wells + economics stages and build the slim artifact payload
    `run_valuation` returns for Claude to build a deal-sheet artifact from.
    See `server.valuation.artifact_payload.build_artifact_payload`."""
    from server.valuation.artifact_payload import build_artifact_payload

    store = ValuationRunStore()
    economics = store.read_stage(run_id, stage="economics")
    if not economics:
        raise ValueError(f"run {run_id}: no economics stage (call run_economics first)")
    wells = store.read_stage(run_id, stage="wells") or {}
    return build_artifact_payload(economics=economics, wells=wells)


def _well_meta_payload(apis: list[str], meta_by_api: dict) -> dict:
    """Per-well facts for the deal sheet, keyed by API. Missing wells → all-None."""
    out: dict[str, dict] = {}
    for api in apis:
        m = meta_by_api.get(api)
        out[api] = {
            "status": m.status if m else None,
            "operator": m.operator if m else None,
            "basin": m.basin if m else None,
            "formation": m.formation if m else None,
            "lateral_ft": m.lateral_ft if m else None,
        }
    return out



def _norm_month_str(m) -> str | None:
    """'YYYY-MM' or 'YYYY-MM[-DD]' → 'YYYY-MM-01'; None when unparseable."""
    if not isinstance(m, str):
        return None
    s = m.strip()
    if len(s) == 7:
        s += "-01"
    try:
        return date.fromisoformat(s[:10]).replace(day=1).isoformat()
    except ValueError:
        return None


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _validate_entry_structure(i: int, entry, violations: list[dict]) -> None:
    """Structural (DB-free) validation of one forecast entry. Appends to
    ``violations``; never raises. Bounds only — judgment is Claude's."""
    def bad(field: str, message: str, well: str | None = None):
        v = {"entry": i, "field": field, "message": message}
        if well:
            v["well"] = well
        violations.append(v)

    if not isinstance(entry, dict):
        bad("entry", "each forecast entry must be an object")
        return
    wells = entry.get("wells")
    if not isinstance(wells, list) or not wells or not all(isinstance(w, str) and w for w in wells):
        bad("wells", "wells must be a non-empty list of well API strings")
    if len(set(wells or [])) != len(wells or []):
        bad("wells", "the same well appears more than once in this entry")

    asserted_any = False
    for s in _STREAMS:
        p = entry.get(s)
        if p is None:
            continue
        asserted_any = True
        if not isinstance(p, dict) or set(p) != _PARAM_FIELDS:
            bad(s, f"{s} must be exactly {{qi, di, b}}; got "
                   f"{sorted(p) if isinstance(p, dict) else type(p).__name__}")
            continue
        if not _is_num(p["qi"]) or p["qi"] <= _QI_MIN:
            bad(f"{s}.qi", f"qi must be a finite number > 0 (units/month at the anchor); got {p['qi']!r}")
        if not _is_num(p["di"]) or not (_DI_RANGE[0] < p["di"] < _DI_RANGE[1]):
            bad(f"{s}.di", f"di must be a nominal MONTHLY decline in ({_DI_RANGE[0]}, {_DI_RANGE[1]}); got {p['di']!r}")
        if not _is_num(p["b"]) or not (_B_RANGE[0] <= p["b"] <= _B_RANGE[1]):
            bad(f"{s}.b", f"b must be in [{_B_RANGE[0]}, {_B_RANGE[1]}]; got {p['b']!r}")
    if not asserted_any:
        bad("oil/gas", "assert at least one stream (oil and/or gas)")

    uptime = entry.get("uptime_factor", 1.0)
    if not _is_num(uptime) or not (_UPTIME_RANGE[0] <= uptime <= _UPTIME_RANGE[1]):
        bad("uptime_factor", f"uptime_factor must be in [{_UPTIME_RANGE[0]}, {_UPTIME_RANGE[1]}]; got {uptime!r}")

    if _norm_month_str(entry.get("anchor_month")) is None:
        bad("anchor_month", "anchor_month is required: 'YYYY-MM' — the month qi applies "
                            "(producers: last clean signal; undrilled: asserted first-production month)")

    rationale = entry.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        bad("rationale", "rationale is required — record the judgments per the well-forecasting skill")

    struck = entry.get("struck_months")
    if struck is not None:
        if not isinstance(struck, list) or any(_norm_month_str(m) is None for m in struck):
            bad("struck_months", "struck_months must be a list of 'YYYY-MM' strings")

    ac = entry.get("analog_cohort")
    if ac is not None:
        _validate_analog_cohort_structure(i, ac, wells if isinstance(wells, list) else [], violations)


def _validate_analog_cohort_structure(i: int, ac, entry_wells: list, violations: list[dict]) -> None:
    """Structural (DB-free) validation of one entry's analog_cohort block.
    Existence-in-DB checks happen later with the other semantic validation."""
    def bad(field: str, message: str):
        violations.append({"entry": i, "field": field, "message": message})

    if not isinstance(ac, dict):
        bad("analog_cohort", "analog_cohort must be an object")
        return
    keys = set(ac)
    if not _COHORT_KEYS_REQ <= keys or not keys <= _COHORT_KEYS_ALL:
        bad("analog_cohort", f"analog_cohort keys must include {sorted(_COHORT_KEYS_REQ)} and may "
                             f"add {sorted(_COHORT_KEYS_ALL - _COHORT_KEYS_REQ)}; got {sorted(keys)}")
        return

    label = ac.get("curve_label")
    if not isinstance(label, str) or not label.strip() or len(label) > 80:
        bad("analog_cohort.curve_label", "curve_label must be a non-empty string (≤ 80 chars); "
                                         "entries sharing a label share one type curve")
    criteria = ac.get("criteria")
    if not isinstance(criteria, str) or not criteria.strip():
        bad("analog_cohort.criteria", "criteria is required — the cohort filter in plain terms "
                                      "(formation, lateral band, vintage, radius)")
    norm = ac.get("normalization", "per_1000ft")
    if norm not in _NORMALIZATIONS:
        bad("analog_cohort.normalization", f"normalization must be one of {_NORMALIZATIONS}")

    kept = ac.get("kept")
    if (not isinstance(kept, list) or not kept
            or not all(isinstance(a, str) and a for a in kept)):
        bad("analog_cohort.kept", "kept must be a non-empty list of analog well API strings")
        return
    if len(kept) != len(set(kept)):
        bad("analog_cohort.kept", "the same analog appears more than once in kept")
    if len(kept) > _MAX_ANALOGS:
        bad("analog_cohort.kept", f"{len(kept)} kept analogs; at most {_MAX_ANALOGS}")

    excluded = ac.get("excluded") or []
    if not isinstance(excluded, list):
        bad("analog_cohort.excluded", "excluded must be a list of {api, reason} objects")
        return
    if len(excluded) > _MAX_ANALOGS:
        bad("analog_cohort.excluded", f"{len(excluded)} excluded analogs; at most {_MAX_ANALOGS}")
    excl_apis: list[str] = []
    for j, e in enumerate(excluded):
        if (not isinstance(e, dict) or set(e) != {"api", "reason"}
                or not isinstance(e.get("api"), str) or not e.get("api")
                or not isinstance(e.get("reason"), str) or not e.get("reason", "").strip()):
            bad("analog_cohort.excluded", f"excluded[{j}] must be exactly {{api, reason}}, both "
                                          "non-empty strings — the reason is the point")
        else:
            excl_apis.append(e["api"])
    if len(excl_apis) != len(set(excl_apis)):
        bad("analog_cohort.excluded", "the same analog appears more than once in excluded")

    overlap = set(kept) & set(excl_apis)
    if overlap:
        bad("analog_cohort", f"analog(s) in both kept and excluded: {sorted(overlap)[:5]}")
    subject_overlap = (set(kept) | set(excl_apis)) & set(a for a in entry_wells if isinstance(a, str))
    if subject_overlap:
        bad("analog_cohort", f"subject well(s) listed as their own analogs: "
                             f"{sorted(subject_overlap)[:5]}")


def forecast_wells_for_run(*, run_id: str | None, forecasts: list[dict], user_id: int = 0) -> dict:
    """Accept-and-echo. Bounds-validate Claude's asserted parameters, persist
    them into the run's single ``forecast`` stage, and return the consequences
    of what was committed (future volumes — never fit quality).

    All-or-nothing per call: any violation bounces the whole call with every
    violation listed and nothing persisted. A valid call MERGES into the
    existing stage — re-asserting a well overwrites just that well; commits are
    cheap and overwritable by design (the skill's revise loop depends on it).

    Cohort entries (len(wells) > 1) persist one scaled curve per member well:
    pro-rata trailing-12 shares per stream. q(t) is linear in qi, so the
    per-well curves sum exactly back to the asserted cohort stream."""
    store = ValuationRunStore()

    if not isinstance(forecasts, list) or not forecasts:
        raise ForecastValidationError(
            [{"field": "forecasts", "message": "forecasts must be a non-empty list of entries"}])

    # Run ownership before anything heavy: a write into a nonexistent run would
    # silently UPDATE 0 rows; a write into someone else's run would be worse.
    if run_id is not None:
        rec = store.get(run_id)
        if rec is None:
            raise ForecastValidationError([{"field": "run_id", "message": f"unknown run_id: {run_id}"}])
        owner = rec.get("user_id")
        if owner is None or int(owner) != int(user_id):
            raise ForecastValidationError([{"field": "run_id", "message": "run_id belongs to another user"}])

    violations: list[dict] = []
    for i, entry in enumerate(forecasts):
        _validate_entry_structure(i, entry, violations)

    # Cross-entry checks need well lists, which only exist when structure holds.
    if not violations:
        seen: dict[str, int] = {}
        total = 0
        for i, entry in enumerate(forecasts):
            for api in entry["wells"]:
                total += 1
                if api in seen:
                    violations.append({"entry": i, "well": api, "field": "wells",
                                       "message": f"{api} already appears in entry {seen[api]}"})
                else:
                    seen[api] = i
        if total > MAX_ASSET_WELLS:
            violations.append({"field": "wells",
                               "message": f"{total} wells across entries; at most {MAX_ASSET_WELLS} per call"})
    if violations:
        raise ForecastValidationError(violations)

    all_wells = [api for entry in forecasts for api in entry["wells"]]
    metas = {m.api: m for m in bulk_load_wells(all_wells)}
    for i, entry in enumerate(forecasts):
        for api in entry["wells"]:
            if api not in metas:
                violations.append({"entry": i, "well": api, "field": "wells",
                                   "message": f"{api} not found in public.wells"})

    # Analog existence + usability, batched: one extra query for every analog
    # referenced anywhere in the call.
    analog_apis = sorted({
        a
        for entry in forecasts if entry.get("analog_cohort")
        for a in (list(entry["analog_cohort"]["kept"])
                  + [e["api"] for e in (entry["analog_cohort"].get("excluded") or [])])
    })
    analog_metas = {m.api: m for m in bulk_load_wells(analog_apis)} if analog_apis else {}
    for i, entry in enumerate(forecasts):
        ac = entry.get("analog_cohort")
        if not ac:
            continue
        for api in ac["kept"]:
            m = analog_metas.get(api)
            if m is None:
                violations.append({"entry": i, "well": api, "field": "analog_cohort.kept",
                                   "message": f"analog {api} not found in public.wells"})
            elif m.n_history_months == 0:
                violations.append({"entry": i, "well": api, "field": "analog_cohort.kept",
                                   "message": f"kept analog {api} has no reported production — it "
                                              "cannot inform a type curve; exclude it with a reason "
                                              "or drop it"})
        for e in ac.get("excluded") or []:
            if e["api"] not in analog_metas:
                violations.append({"entry": i, "well": e["api"], "field": "analog_cohort.excluded",
                                   "message": f"excluded analog {e['api']} not found in public.wells"})
    if violations:
        raise ForecastValidationError(violations)
    prod = bulk_load_production(all_wells)

    current_month = date.today().replace(day=1)
    horizon = config.ECON.horizon_months
    term = config.ECON.terminal_di_annual

    # Semantic validation: anchors against history; cohort trailing production.
    plans: list[dict] = []
    for i, entry in enumerate(forecasts):
        wells_list = entry["wells"]
        anchor_str = _norm_month_str(entry["anchor_month"])
        anchor_d = date.fromisoformat(anchor_str)
        is_cohort = len(wells_list) > 1
        has_history = {api: bool(prod.get(api, {}).get("months")) for api in wells_list}

        for api in wells_list:
            if has_history[api] and anchor_d > current_month:
                violations.append({
                    "entry": i, "well": api, "field": "anchor_month",
                    "message": f"{api} has reported production; anchor_month is the month qi applies "
                               f"and must not be in the future"})
            elif not has_history[api]:
                months_out = (anchor_d.year - current_month.year) * 12 + (anchor_d.month - current_month.month)
                if months_out < 0:
                    violations.append({
                        "entry": i, "well": api, "field": "anchor_month",
                        "message": f"{api} has no reported production; anchor_month is its asserted "
                                   f"first-production month and must be {current_month.strftime('%Y-%m')} or later"})
                elif months_out > _MAX_FUTURE_ANCHOR_MONTHS:
                    violations.append({
                        "entry": i, "well": api, "field": "anchor_month",
                        "message": f"asserted first production for {api} is more than "
                                   f"{_MAX_FUTURE_ANCHOR_MONTHS} months out"})

        shares: dict[str, dict[str, float]] = {}
        for s in _STREAMS:
            if entry.get(s) is None:
                continue
            if not is_cohort:
                shares[s] = {wells_list[0]: 1.0}
                continue
            trailing = {api: cq.trailing_window_cum(prod[api]["months"], prod[api][_PROD_COL[s]],
                                                    anchor=anchor_d)
                        for api in wells_list}
            dry = [api for api, v in trailing.items() if v <= 0.0]
            if dry:
                for api in dry:
                    violations.append({
                        "entry": i, "well": api, "field": s,
                        "message": f"{api} has no trailing-12 {s} production at {anchor_str[:7]} — the "
                                   f"cohort split is pro-rata trailing-12; forecast it individually"})
                continue
            shares[s] = cq.allocation_shares(trailing)
        plans.append({"anchor_str": anchor_str, "anchor_d": anchor_d, "is_cohort": is_cohort,
                      "has_history": has_history, "shares": shares})
    if violations:
        raise ForecastValidationError(violations)

    # Build the per-well stage entries and the echo. Persist only after every
    # entry has built cleanly.
    committed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_entries: dict[str, dict] = {}
    echo_entries: list[dict] = []
    for entry, plan in zip(forecasts, plans):
        wells_list = entry["wells"]
        anchor_str, anchor_d = plan["anchor_str"], plan["anchor_d"]
        uptime = float(entry.get("uptime_factor", 1.0))
        undrilled = not any(plan["has_history"].values())
        warnings: list[str] = []

        ac = entry.get("analog_cohort")
        assertion = {
            "entry_id": uuid.uuid4().hex[:12],
            "asserted": {s: (dict(entry[s]) if entry.get(s) is not None else None) for s in _STREAMS},
            "uptime_factor": uptime,
            "struck_months": [_norm_month_str(m)[:7] for m in (entry.get("struck_months") or [])],
            "rationale": entry["rationale"],
            "cohort": ({"wells": list(wells_list),
                        "shares": {s: {a: round(v, 6) for a, v in m.items()}
                                   for s, m in plan["shares"].items()}}
                       if plan["is_cohort"] else None),
            "analog_cohort": ({
                "curve_label": ac["curve_label"].strip(),
                "criteria": ac["criteria"].strip(),
                "normalization": ac.get("normalization", "per_1000ft"),
                "kept": list(ac["kept"]),
                "excluded": [{"api": e["api"], "reason": e["reason"].strip()}
                             for e in (ac.get("excluded") or [])],
            } if ac else None),
            "committed_at": committed_at,
        }

        for api in wells_list:
            well_entry: dict = {
                "anchor_month": anchor_str[:7],
                "status": metas[api].status,
                # The drilling AFE follows well status, not the anchor: an
                # anchored DUC still gets its capex, placed at the asserted
                # online month by the schedule.
                "needs_capex": config.status_code(metas[api].status) in ("DUC", "PUD"),
                "assertion": assertion,
            }
            for s in _STREAMS:
                p = entry.get(s)
                if p is None:
                    curve = make_zero_curve(s)
                else:
                    share = plan["shares"][s][api]
                    # Uptime is applied as a qi haircut (curve × factor ≡ curve
                    # with qi × factor — q(t) is linear in qi). Order: share
                    # then uptime; equivalent either way, documented here.
                    curve = make_curve(p["qi"] * share * uptime, p["di"], p["b"],
                                       stream=s, terminal_di_annual=term)
                well_entry[s] = {"curve": _serialize_curve(curve)}
            new_entries[api] = well_entry

        echo: dict = {"wells": list(wells_list), "anchor_month": anchor_str[:7], "undrilled": undrilled}
        if undrilled:
            echo["online_month"] = anchor_str[:7]
        laterals = [metas[a].lateral_ft for a in wells_list]
        lateral_total = float(sum(laterals)) if all(bool(l) for l in laterals) else None
        last_reported = max((prod[a]["months"][-1] for a in wells_list if prod[a]["months"]),
                            default=None)
        for s in _STREAMS:
            p = entry.get(s)
            trailing_sum = sum(cq.trailing_window_cum(prod[a]["months"], prod[a][_PROD_COL[s]],
                                                      anchor=anchor_d)
                               for a in wells_list)
            if p is None:
                echo[s] = None
                if trailing_sum > 0:
                    warnings.append(f"{s} not asserted but trailing-12 {s} was "
                                    f"{round(trailing_sum, 1)} — it will contribute zero revenue")
                continue
            cum = sum(cq.cum_through(prod[a]["months"], prod[a][_PROD_COL[s]], anchor=anchor_d)
                      for a in wells_list)
            entry_curve = make_curve(p["qi"] * uptime, p["di"], p["b"],
                                     stream=s, terminal_di_annual=term)
            echo[s] = cq.stream_consequences(
                entry_curve, anchor=anchor_d, horizon_months=horizon,
                trailing_12_actual=None if undrilled else trailing_sum,
                cum_to_date=cum, lateral_ft=lateral_total,
                anchor_is_future=undrilled)
            if p["di"] <= term / 12.0:
                warnings.append(f"{s}: asserted di ({p['di']}) is at/below the terminal monthly "
                                f"rate — the curve never steepens to the terminal tail")
        if last_reported and anchor_str > last_reported:
            warnings.append(f"anchor {anchor_str[:7]} is after the last reported month "
                            f"({last_reported[:7]}) — fine if you mean current capacity, "
                            f"but no reported data backs it")
        if plan["is_cohort"]:
            echo["shares"] = {s: {a: round(v, 4) for a, v in m.items()}
                              for s, m in plan["shares"].items()}
        if ac:
            echo["analog_cohort"] = {"curve_label": ac["curve_label"].strip(),
                                     "kept": len(ac["kept"]),
                                     "excluded": len(ac.get("excluded") or [])}
        if warnings:
            echo["warnings"] = warnings
        echo_entries.append(echo)

    if run_id is None:
        run_id = store.new_run(user_id=user_id, case_file={})
    existing = store.read_stage(run_id, stage="forecast") or {}
    merged = dict(existing.get("forecasts") or {})
    merged.update(new_entries)
    store.write_stage(run_id, stage="forecast", payload={"forecasts": merged})

    by_status = {code: 0 for code in config.ECON.default_rate_centers}
    for fc in merged.values():
        by_status[config.status_code(fc.get("status"))] += 1
    return {
        "run_id": run_id,
        "committed": echo_entries,
        "wells_committed": len(new_entries),
        "wells_in_run": len(merged),
        "by_status": by_status,
    }


def _load_forecast_stage(*, forecast: dict, as_of, months_override):
    """Place the single dateless `forecast` stage on the calendar for economics.

    Asserted stages (the accept-and-echo path): every well carries an
    ``anchor_month`` — producers anchor where qi applies, undrilled wells at
    their asserted first-production month — and curves anchor at t=0
    (peak == anchor), so start = peak = anchor.

    Legacy fit-era stages replay unchanged: per-stream ``peak_month`` keeps
    project()'s peak_offset correct (their qi was a peak rate, not an anchor
    rate); wells with no anchor fall back to the status-derived planned
    first-prod date (else as_of) — the only surviving use of the DUC/PERMITTED
    config offsets; and ``needs_capex`` falls back to the fit-era
    ``classification == "no_history"`` trigger."""
    def _norm(d: str | None) -> str | None:
        """Normalize a 'YYYY-MM' partial date to 'YYYY-MM-01' for fromisoformat."""
        return d if (d is None or len(d) != 7) else d + "-01"

    forecasts: dict[str, dict] = {}
    needs_capex: dict[str, bool] = {}
    statuses: dict[str, str] = {}
    for api, fc in (forecast.get("forecasts") or {}).items():
        strat = fc.get("strategy") or ("asserted" if "assertion" in fc else "pure_analog")
        anchor = fc.get("anchor_month")
        if anchor:
            start = _norm(anchor)
            oil_peak = _norm(fc["oil"].get("peak_month")) or start
            gas_peak = _norm(fc["gas"].get("peak_month")) or start
            forecasts[api] = {
                "oil": _place_curve(self_curve=fc["oil"]["curve"], start_date=start,
                                    strategy=strat, peak_date=oil_peak),
                "gas": _place_curve(self_curve=fc["gas"]["curve"], start_date=start,
                                    strategy=strat, peak_date=gas_peak),
            }
        else:
            online = config.planned_first_prod_date(
                fc.get("status"), as_of=as_of, months_override=months_override)
            start = str(online or as_of)
            forecasts[api] = {
                "oil": _place_curve(self_curve=fc["oil"]["curve"], start_date=start, strategy=strat),
                "gas": _place_curve(self_curve=fc["gas"]["curve"], start_date=start, strategy=strat),
            }
        needs_capex[api] = bool(fc.get("needs_capex", fc.get("classification") == "no_history"))
        statuses[api] = fc.get("status") or "PUD"
    return forecasts, needs_capex, statuses


def run_valuation_for_run(*, run_id: str, params: dict) -> dict:
    """Read the single forecast stage, place wells on the calendar, run economics,
    assemble the deal sheet. params is the validated deal terms (interest +
    economics_overrides + asset_list)."""
    case = parse_run_params(params)        # raises CaseFileError on bad params
    interest_type = case.interest_type
    store = ValuationRunStore()
    forecast = store.read_stage(run_id, stage="forecast")
    if not forecast:
        raise ValueError(f"run {run_id}: no forecast stage — call forecast_wells first")

    econ_overrides = dict(params.get("economics_overrides") or {})
    # Fold interest into econ_overrides so the economics core is self-contained.
    econ_overrides["interest_type"] = interest_type
    econ_overrides["interest"] = params.get("interest")
    as_of = config.resolve_as_of(econ_overrides.get("effective_date"), today=date.today())
    months_override = econ_overrides.get("months_to_first_prod")

    forecasts, needs_capex, statuses = _load_forecast_stage(
        forecast=forecast, as_of=as_of, months_override=months_override)

    econ = _economics_from_forecasts(
        forecasts=forecasts, needs_capex=needs_capex,
        statuses=statuses, econ_overrides=econ_overrides)
    store.write_stage(run_id, stage="economics", payload=econ)

    # Reload meta for the deal-sheet facts/buckets (correct regardless of stages).
    apis = list(forecasts)
    meta_by_api = {m.api: m for m in bulk_load_wells(apis)}

    # Evidence: the per-assertion judgment record (histories, committed curves,
    # per-well PV, hydrated analog cohorts). Built from the RAW forecast stage —
    # it needs the assertions, not the calendar-placed curves.
    prod = bulk_load_production(apis)
    kept_analogs, all_analogs = collect_analog_apis(forecast)
    analog_meta = {m.api: m for m in bulk_load_wells(all_analogs)} if all_analogs else {}
    analog_prod = bulk_load_production(kept_analogs) if kept_analogs else {}
    evidence = build_evidence(
        forecast=forecast, schedule=econ["schedule"], meta_by_api=meta_by_api,
        prod=prod, analog_meta=analog_meta, analog_prod=analog_prod,
        rate_centers=econ["rate_centers"],
    )

    store.write_stage(run_id, stage="wells", payload={
        "well_meta": _well_meta_payload(apis, meta_by_api),
        "statuses": {a: (meta_by_api[a].status if a in meta_by_api else None) for a in apis},
        "needs_capex": needs_capex,
        "evidence": evidence,
    })

    return {"run_id": run_id, "npv_at_centers": econ["npv_at_centers"]}
