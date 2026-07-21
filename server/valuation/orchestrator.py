"""Valuation orchestrator. Runs forecast_wells → economics → deal-sheet assembly."""
import math
from datetime import date

import numpy as np
from dateutil.relativedelta import relativedelta

from server.valuation import config
from server.valuation import strip
from server.valuation.casefile import MAX_ASSET_WELLS, parse_run_params
from server.valuation.routing import (
    classify_well, build_curve, AnalogRequired, WellState,
)
from server.valuation.econ import cashflow_components, compute_gross_revenue, npv, resolve_well_interest
from server.valuation.forecast import fit_curve, override_b, percentile_curves, project
from server.valuation.run_record import ValuationRunStore
from server.valuation.types import DeclineCurve, Forecast, ForecastProvenance, WellMeta
from server.valuation.wells import bulk_load_production, bulk_load_wells


class CohortError(Exception):
    """Raised when no analog well can be fit into a type curve."""


class AnalogsRequired(Exception):
    """Bounce: one or more groups have wells needing analogs but supplied none."""
    def __init__(self, needs_analogs: list[dict]):
        self.needs_analogs = needs_analogs
        super().__init__("analogs_required")


# Server-default b when no cohort exists (all-history deal). Basin-typical
# unconventional oil. The plan picks 0.8.
_SERVER_DEFAULT_B = 0.8

# Cohort-b gating: b is only sourced from analogs mature enough to identify it
# (fit_curve's own docstring: poorly identified under ~24 post-peak months), and
# the sourced value is clamped to a sane unconventional band. Backtested
# 2026-07 (results/backtest_baseline_v1.json): consistent bias reduction vs the
# ungated median. qi/di stay full-cohort medians — young modern-completion
# analogs are the right source for rate level, just not for tail curvature.
_GATED_B_MIN_POST_PEAK = 24
_B_CLAMP = (0.3, 1.3)

_PLAN_FIELDS = {"cohort", "b"}


def validate_plan(plan: dict | None) -> dict:
    """Two-field plan: cohort (optional override) + b (optional override).

    Reject unknown fields aggressively — every field this grows is justified
    by a real deal that the current set couldn't express.

    Passes ``None`` through as ``{}`` (server uses defaults).
    """
    if plan is None:
        return {}
    if not isinstance(plan, dict):
        raise ValueError(f"plan must be an object, got {type(plan).__name__}")
    unknown = set(plan.keys()) - _PLAN_FIELDS
    if unknown:
        raise ValueError(f"unknown plan field(s): {sorted(unknown)}")
    if "b" in plan:
        b = plan["b"]
        if b == "cohort_median":
            pass                                   # server resolves
        elif isinstance(b, (int, float)) and not isinstance(b, bool):
            if not (0.001 <= b <= 2.0):
                raise ValueError(f"b must be in [0.001, 2.0] or 'cohort_median', got {b!r}")
        else:
            raise ValueError(f"b must be a number or 'cohort_median', got {b!r}")
    if "cohort" in plan and not isinstance(plan["cohort"], dict):
        raise ValueError("cohort must be an object")
    return plan


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
        "qi_peak": c.qi_peak, "di": c.di, "b": c.b,
        "terminal_di_monthly": c.terminal_di_monthly,
        "switch_month_from_peak": switch if math.isfinite(switch) else None,
        "stream": c.stream,
        "provenance": {"source": c.provenance.source, "strategy": c.provenance.strategy},
    }


def _deserialize_curve(c: dict) -> DeclineCurve:
    """Inverse of _serialize_curve. None switch month → float('inf').
    provenance is optional — curve dicts without it (e.g. raw dateless curves
    stored by the new forecast_wells stages) get a synthetic provenance."""
    switch = c["switch_month_from_peak"]
    if switch is None:
        switch = float("inf")
    prov = c.get("provenance") or {}
    return DeclineCurve(
        qi_peak=c["qi_peak"], di=c["di"], b=c["b"],
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
    classifications: dict,
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
            if classifications.get(api) == "no_history" and offset < horizon:
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


def _economics_from_forecasts(*, forecasts: dict, classifications: dict,
                              statuses: dict, econ_overrides: dict) -> dict:
    """Pure economics: monthly schedule → risked-PV cube → NPV. Takes the
    assembled (already calendar-placed) forecasts + classifications + statuses.
    Every economic number is read from econ_overrides (the validated params)."""
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
        forecasts=forecasts, classifications=classifications, origin=origin,
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



def _build_type_curve_with_stats(prod: dict, stream: str):
    """Median type curve from analog fits, plus fit stats and b provenance.

    Returns ``(curve, n_fit, n_skipped, b_meta)``. qi/di/terminal are the
    full-cohort parameter-wise medians of free fits (unchanged); the cohort b is
    GATED — median only of analogs with ≥ ``_GATED_B_MIN_POST_PEAK`` post-peak
    months, clamped to ``_B_CLAMP``, falling back to ``_SERVER_DEFAULT_B`` when
    no analog is mature enough to identify b. ``b_meta`` records which path won
    (``{"b": float, "source": str, "n_mature": int}``) and flows to
    ``analogs_used`` so the agent can see when the cohort was too young.

    ``prod`` is a preloaded bulk_load_production result (caller loads once and
    passes to both oil and gas calls — avoids double DB round-trip)."""
    q_col = "oil_bbl" if stream == "oil" else "gas_mcf"
    curves = []
    mature_bs: list[float] = []
    for _api, d in prod.items():
        q = np.asarray(d[q_col], dtype=float)
        try:
            c = fit_curve(np.arange(len(q), dtype=float), q, stream=stream, b_fixed=None)
        except ValueError:
            continue
        curves.append(c)
        if len(q) - 1 - int(np.argmax(q)) >= _GATED_B_MIN_POST_PEAK:
            mature_bs.append(c.b)
    n_fit, n_skipped = len(curves), len(prod) - len(curves)
    if not curves:
        raise CohortError(f"no analog fit for stream={stream} ({len(prod)} tried)")
    cohort = percentile_curves(curves, pct=0.5)
    if mature_bs:
        b = min(max(float(np.median(mature_bs)), _B_CLAMP[0]), _B_CLAMP[1])
        source = f"gated_median(n={len(mature_bs)})"
    else:
        b = _SERVER_DEFAULT_B
        source = "default_no_mature_analogs"
    b_meta = {"b": round(b, 4), "source": source, "n_mature": len(mature_bs)}
    return override_b(cohort, b, note=f"b:{source}"), n_fit, n_skipped, b_meta


def _classify_overall(d: dict) -> WellState:
    """Gas-aware overall state for cohort-need + summary. Gas-only wells (zero oil,
    real gas) classify off gas so they aren't mislabeled HISTORY on a zero stream."""
    q_oil = np.asarray(d.get("oil_bbl", []), dtype=float)
    q_gas = np.asarray(d.get("gas_mcf", []), dtype=float)
    if q_oil.sum() <= 0 and len(q_gas) and q_gas.sum() > 0:
        return classify_well(d.get("months", []), q_gas)
    return classify_well(d.get("months", []), q_oil)


_NEEDS_ANALOG = {WellState.THIN_PEAKED, WellState.CLIMBING, WellState.NO_HISTORY}


def forecast_wells_for_run(*, run_id: str | None, groups: list[dict], user_id: int = 0) -> dict:
    """Classify every subject well, bounce (all-or-nothing) if a group needs
    analogs and has none, fit each group's analogs into a median type curve, blend
    per the routing table, and write ONE dateless `forecast` stage."""
    if not groups:
        raise ValueError("forecast_wells requires a non-empty groups list")

    store = ValuationRunStore()

    # Load all subjects once.
    all_subjects = [a for g in groups for a in (g.get("wells") or [])]
    if not all_subjects:
        raise ValueError("forecast_wells: every group must list at least one well")
    metas = {m.api: m for m in bulk_load_wells(all_subjects)}
    missing = [a for a in all_subjects if a not in metas]
    if missing:
        raise ValueError(f"{len(missing)} well API(s) not found in public.wells: {missing[:5]}")
    subj_prod = bulk_load_production(all_subjects)

    # First pass: classify + detect bounces. No writes until every group passes.
    overall: dict[str, WellState] = {}
    needs_analogs: list[dict] = []
    for g in groups:
        wells = g.get("wells") or []
        analogs = g.get("analogs") or []
        short = []
        for api in wells:
            st = _classify_overall(subj_prod.get(api, {"months": [], "oil_bbl": [], "gas_mcf": []}))
            overall[api] = st
            if st in _NEEDS_ANALOG and not analogs:
                short.append(api)
        if short:
            needs_analogs.append({"area": g.get("area"), "wells": short})
    if needs_analogs:
        raise AnalogsRequired(needs_analogs)

    # Second pass: fit analogs per group, build per-well curves, accumulate.
    # Nothing is minted or written until EVERY well in every group has a curve —
    # a per-stream AnalogRequired here (e.g. an oil-HISTORY well whose gas
    # stream is CLIMBING on rising GOR, in a group with no analogs) becomes a
    # clean AnalogsRequired bounce, exactly like the first-pass check.
    forecasts: dict[str, dict] = {}
    group_meta: list[dict] = []
    return_groups: list[dict] = []
    stream_short: list[dict] = []
    from collections import defaultdict
    oil_by_month: dict[str, float] = defaultdict(float)
    gas_by_month: dict[str, float] = defaultdict(float)

    for g in groups:
        wells = g.get("wells") or []
        analogs = g.get("analogs") or []
        oil_tc = gas_tc = None
        n_fit = n_skipped = 0
        b_meta_oil = None
        if analogs:
            analog_prod = bulk_load_production(analogs)
            oil_tc, n_fit, n_skipped, b_meta_oil = _build_type_curve_with_stats(analog_prod, "oil")
            gas_tc, _, _, _ = _build_type_curve_with_stats(analog_prod, "gas")

        by_status: dict[str, list] = {"PDP": [], "DUC": [], "PUD": []}
        spectrum = {s.value: 0 for s in WellState}
        short: list[str] = []
        for api in wells:
            d = subj_prod.get(api, {"months": [], "oil_bbl": [], "gas_mcf": []})
            q_oil = np.asarray(d["oil_bbl"], dtype=float)
            q_gas = np.asarray(d["gas_mcf"], dtype=float)
            try:
                oil_curve, _st, oil_strat = build_curve(d["months"], q_oil, analog=oil_tc, stream="oil")
                gas_curve, _gst, _gstrat = build_curve(d["months"], q_gas, analog=gas_tc, stream="gas")
            except AnalogRequired:
                short.append(api)
                continue
            st = overall[api]
            spectrum[st.value] += 1
            status = metas[api].status
            anchor = d["months"][-1] if d["months"] else None
            entry = {
                "oil": {"curve": _serialize_curve(oil_curve)},
                "gas": {"curve": _serialize_curve(gas_curve)},
                "classification": st.value,
                "strategy": oil_strat,
                "status": status,
            }
            if anchor:
                entry["anchor_month"] = anchor
                # Per-stream historical peak month so _load_forecast_stage can
                # place the curve at the right offset (project() expects
                # peak_offset = months(peak → anchor)).
                entry["oil"]["peak_month"] = d["months"][int(np.argmax(q_oil))]
                entry["gas"]["peak_month"] = d["months"][int(np.argmax(q_gas))]
            forecasts[api] = entry
            bucket = config.status_code(status)   # "PDP" | "DUC" | "PUD"
            by_status[bucket].append({
                "api": api, "strategy": oil_strat, "status": status,
                "months_producing": len(d["months"]),
            })
            for i, mo in enumerate(d["months"]):
                oil_by_month[mo] += float(d["oil_bbl"][i])
                gas_by_month[mo] += float(d["gas_mcf"][i])

        if short:
            stream_short.append({"area": g.get("area"), "wells": short})
        gm = {"area": g.get("area")}
        if oil_tc is not None:
            gm["type_curve"] = {"oil": _serialize_curve(oil_tc), "gas": _serialize_curve(gas_tc)}
            gm["analog_meta"] = {"analog_apis": list(analogs), "n_fit": n_fit,
                                 "n_skipped": n_skipped, "b_meta": b_meta_oil}
        group_meta.append(gm)
        analogs_used = {"n_requested": len(analogs), "n_fit": n_fit, "n_skipped": n_skipped}
        if b_meta_oil is not None:
            analogs_used["cohort_b"] = b_meta_oil
        return_groups.append({
            "area": g.get("area"), "by_status": by_status, "spectrum": spectrum,
            "analogs_used": analogs_used,
        })

    if stream_short:
        raise AnalogsRequired(stream_short)

    if run_id is None:
        run_id = store.new_run(user_id=user_id, case_file={})

    ordered = sorted(oil_by_month)
    actual_history = {
        "dates": ordered,
        "oil": [round(oil_by_month[m], 1) for m in ordered],
        "gas": [round(gas_by_month[m], 1) for m in ordered],
    }
    store.write_stage(run_id, stage="forecast", payload={
        "forecasts": forecasts, "groups": group_meta, "actual_history": actual_history,
    })
    return {"run_id": run_id, "groups": return_groups}


def _load_forecast_stage(*, forecast: dict, as_of, months_override):
    """Place the single dateless `forecast` stage on the calendar for economics.
    Producing wells (have anchor_month) anchor at their last history month; others
    anchor at the status-derived planned first-prod date (else as_of).

    For producing wells, each stream's stored peak_month is passed as peak_date so
    project() computes the correct peak_offset (months elapsed from historical peak
    to anchor). This makes the decline continue from the anchor rate rather than
    restart at qi_peak. CLIMBING wells' argmax IS the last month (peak==anchor,
    peak_offset==0) so they are already correct and unchanged by this path."""
    def _norm(d: str | None) -> str | None:
        """Normalize a 'YYYY-MM' partial date to 'YYYY-MM-01' for fromisoformat."""
        return d if (d is None or len(d) != 7) else d + "-01"

    forecasts: dict[str, dict] = {}
    classifications: dict[str, str] = {}
    statuses: dict[str, str] = {}
    for api, fc in (forecast.get("forecasts") or {}).items():
        strat = fc.get("strategy", "pure_analog")
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
        classifications[api] = fc.get("classification", "no_history")
        statuses[api] = fc.get("status") or "PUD"
    return forecasts, classifications, statuses


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

    forecasts, classifications, statuses = _load_forecast_stage(
        forecast=forecast, as_of=as_of, months_override=months_override)

    econ = _economics_from_forecasts(
        forecasts=forecasts, classifications=classifications,
        statuses=statuses, econ_overrides=econ_overrides)
    store.write_stage(run_id, stage="economics", payload=econ)

    # Reload meta for the deal-sheet facts/buckets (correct regardless of stages).
    apis = list(forecasts)
    meta_by_api = {m.api: m for m in bulk_load_wells(apis)}
    store.write_stage(run_id, stage="wells", payload={
        "well_meta": _well_meta_payload(apis, meta_by_api),
        "statuses": {a: (meta_by_api[a].status if a in meta_by_api else None) for a in apis},
        "classifications": classifications,
    })

    return {"run_id": run_id, "npv_at_centers": econ["npv_at_centers"]}
