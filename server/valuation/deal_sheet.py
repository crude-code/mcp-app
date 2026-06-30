"""Pure assembly of the valuation `deal_sheet` widget spec from run-record data.

No DB, no I/O. Inputs are plain dicts read from the wells/economics/forecast
stages; output is the JSON-able widget spec the renderer's DealSheet component
consumes. Keeps `compose_briefing_for_run` thin and these transforms testable.
"""
from collections import Counter, defaultdict
from datetime import date

import numpy as np

from server.valuation import config
from server.valuation import forecast as fc_engine
from server.valuation.econ import resolve_well_interest

# Display order + labels/tags for the three status buckets. Colors are EI
# semantic CSS vars resolved in the renderer.
_STATUS_DISPLAY = [
    {"code": "PDP", "label": "Producing", "tag": "(PDP)", "dot": "var(--change-up)"},
    {"code": "DUC", "label": "DUC", "tag": "+18mo", "dot": "var(--content-accent)"},
    {"code": "PUD", "label": "Permitted", "tag": "(PUD) +36mo", "dot": "var(--text-dim)"},
]


def _titlecase(text: str | None) -> str:
    return " ".join(w.capitalize() for w in (text or "").split())


def _modal_operator(well_meta: dict) -> str:
    ops = [m.get("operator") for m in well_meta.values() if m.get("operator")]
    if not ops:
        return "—"
    counts = Counter(ops)
    distinct = len(counts)
    top = counts.most_common(1)[0][0]
    label = _titlecase(top)
    return f"{label} +{distinct - 1}" if distinct > 1 else label


def _area(well_meta: dict) -> str:
    basins = Counter(m.get("basin") for m in well_meta.values() if m.get("basin"))
    form_counts = Counter(m.get("formation") for m in well_meta.values() if m.get("formation"))
    forms = [_titlecase(f) for f, _ in form_counts.most_common()]
    basin = _titlecase(basins.most_common(1)[0][0]) if basins else "—"
    if not forms:
        return basin
    return f"{basin} · {'/'.join(forms)}"


def _well_net_fraction(interest: dict, api: str) -> float:
    """Net-WELL fraction for one well: working interest for WI, decimal for
    minerals. A `by_api` override wins over the blanket value."""
    itype = interest["interest_type"]
    eff = resolve_well_interest(
        itype, api, wi_pct=interest.get("wi_pct"), nri_pct=interest.get("nri_pct"),
        decimal=interest.get("decimal"), by_api=interest.get("by_api"),
    )
    return eff["wi_pct"] if itype == "wi" else eff["decimal"]


def _interest_facts(interest: dict, well_meta: dict) -> tuple[str, str]:
    """Returns (deal_type, interest_label). The label shows the blanket terms
    when interest is uniform, else flags per-well variation with the average."""
    itype = interest["interest_type"]
    apis = list(well_meta) or list(interest.get("by_api") or {})
    if interest.get("by_api") and apis:
        avg = sum(_well_net_fraction(interest, a) for a in apis) / len(apis)
        if itype == "minerals":
            return "Minerals / Royalty", f"per-well · avg {avg * 100:.2f}% decimal"
        return "Working Interest", f"per-well · avg {avg * 100:g}% WI"
    if itype == "minerals":
        return "Minerals / Royalty", f"{float(interest['decimal']) * 100:.2f}% decimal"
    wi = float(interest["wi_pct"])
    nri = float(interest["nri_pct"])
    return "Working Interest", f"{wi * 100:g}% WI · {nri * 100:g}% NRI"


def roll_up_facts(well_meta: dict, interest: dict, rate_centers: dict) -> tuple[dict, list[dict]]:
    """Build the exec-summary facts grid + the per-status display rows.

    `well_meta`: api → {status, operator, basin, formation}. `interest`:
    {interest_type, wi_pct/nri_pct | decimal, by_api?}. `rate_centers`:
    {PDP, DUC, PUD} → center annual rate (decimal). Returns
    `(facts, statuses)` where statuses is in fixed PDP/DUC/PUD order with gross
    counts (by `config.status_code`) and net counts (sum of each well's net
    fraction within the bucket — so per-well ownership rolls up correctly).
    """
    deal_type, interest_label = _interest_facts(interest, well_meta)
    facts = {
        "deal_type": deal_type,
        "interest": interest_label,
        "operator": _modal_operator(well_meta),
        "area": _area(well_meta),
    }

    gross: Counter = Counter()
    net_by_code: dict[str, float] = defaultdict(float)
    for api, m in well_meta.items():
        code = config.status_code(m.get("status"))
        gross[code] += 1
        net_by_code[code] += _well_net_fraction(interest, api)

    statuses = []
    for disp in _STATUS_DISPLAY:
        code = disp["code"]
        statuses.append({
            **disp,
            "gross_wells": int(gross.get(code, 0)),
            "net_wells": round(net_by_code.get(code, 0.0), 2),
            "rates": [_fmt_rate(r) for r in config.rate_ladder(rate_centers[code])],
        })
    return facts, statuses


def _fmt_rate(rate: float) -> str:
    """0.175 → '17.5' — must match orchestrator._rate_label (the cube's keys)."""
    return f"{rate * 100:g}"


# Minimum visible window when there is only a single online event (the user's
# "+12 months after additional production" rule is undefined for one well, and
# a lone PDP deal would otherwise cram into 12 months).
_MIN_WINDOW_MONTHS = 24


def _online_offset(code: str) -> int:
    """Month offset from the NPV origin at which a status comes online."""
    if code == "DUC":
        return config.ECON.duc_months_to_first_prod
    if code == "PUD":
        return config.ECON.permit_months_to_first_prod
    return 0  # PDP produces from the origin


def _add_months(origin_iso: str, months: int) -> str:
    """'2026-07-01' + N months → 'YYYY-MM' (calendar label for the x-axis)."""
    y, m, *_ = origin_iso.split("-")
    total = int(y) * 12 + (int(m) - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def build_production_series(
    *, schedule_totals: dict, horizon_months: int, origin: str,
    statuses: list[dict], step: int = 1,
) -> dict:
    """Net monthly oil/gas/cashflow over the economically active window only.

    The window is anchored at the first producing month and runs through
    ``max(last_online + 12, first_prod + _MIN_WINDOW_MONTHS)`` (clamped to the
    horizon), so the 30-year dead tail and the pre-online flat zero line are
    dropped. `last_online` is the online offset of the latest *present* status
    (PDP→0, DUC→+18mo, PUD→+36mo).

    `schedule_totals` carries `net_oil`/`net_gas`/`net_cashflow` arrays (index =
    month offset from `origin`) — already net of each well's revenue interest
    and summed across wells. Each point gets a calendar `date` (`"YYYY-MM"`) so
    the renderer plots a real time axis. `statuses` is the `roll_up_facts` list
    (only `code` + `gross_wells` are read).
    """
    oil = schedule_totals.get("net_oil", [])
    gas = schedule_totals.get("net_gas", [])
    cash = schedule_totals.get("net_cashflow", [])

    span = min(horizon_months, max(len(oil), len(gas)))
    first_prod = next(
        (i for i in range(span)
         if (i < len(oil) and oil[i] > 0) or (i < len(gas) and gas[i] > 0)),
        0,
    )
    present = [s["code"] for s in statuses if s.get("gross_wells", 0) > 0]
    last_online = max((_online_offset(c) for c in present), default=0)
    end = min(max(last_online + 12, first_prod + _MIN_WINDOW_MONTHS), horizon_months - 1)

    series = [
        {
            "m": i,
            "date": _add_months(origin, i),
            "oil": round(float(oil[i]), 1) if i < len(oil) else 0.0,
            "gas": round(float(gas[i]), 1) if i < len(gas) else 0.0,
            "cashflow": round(float(cash[i])) if i < len(cash) else 0,
        }
        for i in range(first_prod, end + 1, step)
    ]
    return {
        "series": series,
        "start_month": first_prod,
        "end_month": end,
        "origin": origin,
    }


def _default_rates(rate_centers: dict) -> dict:
    """Default selection = each status's center rung. Derived from
    `config.rate_ladder(center)[1]` (the rounded middle rung) so the label is
    byte-identical to the matching `rates` entry and the cube key."""
    return {code: _fmt_rate(config.rate_ladder(center)[1]) for code, center in rate_centers.items()}


def build_deal_sheet_spec(
    *, headline: str, tldr: str, title: str, facts: dict, statuses: list[dict],
    cube: dict, production: dict, rate_centers: dict, price_mode: str = "strip",
    run_id: str | None = None,
) -> dict:
    """Assemble the briefing spec carrying a single `deal_sheet` widget.

    `layout: "deal_sheet"` flags SpecRenderer to render the widget full-bleed
    (no BriefingHeader / section chrome). `headline_npv` is the default-view
    risk-weighted total (sum of the three center cells at the base deck), kept
    for narration — equal to the economics stage's npv_at_centers.total.
    """
    labels, deck = config.deck_labels(price_mode)
    rates = _default_rates(rate_centers)
    headline_npv = round(sum(cube[deck][code][rates[code]] for code in rates), 2)

    widget = {
        "type": "deal_sheet",
        "title": title,
        "tldr": tldr,
        "facts": facts,
        "decks": labels,
        "default_deck": deck,
        "default_rates": rates,
        "statuses": statuses,
        "cube": cube,
        "production": production,
        "run_id": run_id,
    }
    return {
        "kind": "briefing",
        "layout": "deal_sheet",
        "headline": headline,
        "tldr": tldr,
        "headline_npv": headline_npv,
        "sections": [{"layout": "full-width", "widgets": [widget]}],
    }


# ── Advanced "Behind the Valuation" block (Asset / Production / Econ) ─────────
# Additive to the deal_sheet spec; pure assembly from the persisted stages.


def _lateral_band(lateral_ft: float | None) -> str:
    """Lateral length → nearest-mile display band. None/<=0 → 'unknown'."""
    if not lateral_ft or lateral_ft <= 0:
        return "unknown"
    miles = round(lateral_ft / 5280.0)
    return f"{miles}-mile"


def build_asset_block(well_meta: dict) -> dict:
    """Asset-composition view: facts + (status, lateral, formation) groups.

    `well_meta`: api → {status, operator, basin, formation, lateral_ft}. Status
    is mapped to the PDP/DUC/PUD bucket via config.status_code.
    """
    counts: Counter = Counter()
    formations: Counter = Counter()
    for m in well_meta.values():
        code = config.status_code(m.get("status"))
        band = _lateral_band(m.get("lateral_ft"))
        form = m.get("formation") or "—"
        counts[(code, band, form)] += 1
        if m.get("formation"):
            formations[m["formation"]] += 1
    groups = [
        {"status": code, "lateral_band": band, "formation": form, "n_wells": n}
        for (code, band, form), n in sorted(counts.items(), key=lambda kv: kv[0])
    ]
    return {
        "operator": _modal_operator(well_meta),
        "area": _area(well_meta),
        "formations": [f for f, _ in formations.most_common()],
        "groups": groups,
        "total_wells": sum(counts.values()),
    }


def build_econ_block(*, inputs: dict, interest: dict, effective_date: str) -> dict:
    """Assumptions dump for the Econ tab. Prices from the persisted economics
    `inputs`; cost/timing defaults from config.ECON. Realized = deck − diff
    (diffs are signed discounts: positive = sells below benchmark; econ.py
    subtracts them)."""
    e = config.ECON
    itype = interest.get("interest_type")
    interest_out: dict = {"type": itype}
    if itype == "wi":
        interest_out["wi_pct"] = interest.get("wi_pct")
        interest_out["nri_pct"] = interest.get("nri_pct")
    else:
        interest_out["decimal"] = interest.get("decimal")
    return {
        "price": {
            "mode": inputs.get("price_mode", "flat"),
            "strip_trade_date": inputs.get("strip_trade_date"),
            "oil_deck": inputs["oil_price"], "gas_deck": inputs["gas_price"],
            "oil_diff": inputs["oil_diff"], "gas_diff": inputs["gas_diff"],
            "oil_realized": round(inputs["oil_price"] - inputs["oil_diff"], 2),
            "gas_realized": round(inputs["gas_price"] - inputs["gas_diff"], 2),
        },
        # Opex/capex are deal-level inputs (resolved from economics_overrides at
        # run time), not global config — so read them off `inputs`, falling back
        # to the config default only when the run didn't carry them.
        "costs": {
            "opex_var": inputs.get("opex_per_bbl_usd", e.opex_per_bbl_usd),
            "opex_fixed": inputs.get("opex_per_well_per_month_usd", e.opex_per_well_per_month_usd),
            "drilling_afe": inputs.get("capex_per_well_usd", e.capex_per_well_usd),
            "sev_tax_pct": inputs["tax_pct"],
            "gpt_pct": inputs["gpt_pct"],
        },
        "interest": interest_out,
        "timing": {
            "effective_date": effective_date,
            "horizon_months": inputs["horizon_months"],
            "online_lag": {"DUC": e.duc_months_to_first_prod, "PUD": e.permit_months_to_first_prod},
        },
    }


def build_production_estimates(
    *, producing_forecasts: list[dict], cohort_curves: dict | None, cohort_diag: dict | None,
    non_producing_count: int, actual_history: dict, origin: str, window_months: int = 120,
) -> list[dict]:
    """Production-tab estimates. v1: PDP aggregate (history) + one cohort type curve.

    PHASE-IT BOUNDARY: when the engine builds N cohorts, pass N cohort curves/diags
    here and emit N cohort estimates — nothing downstream changes.

    `producing_forecasts`: [{oil: Forecast, gas: Forecast}] for PDP wells.
    `cohort_curves`: {oil: DeclineCurve, gas: DeclineCurve} | None.
    `actual_history`: {dates, oil, gas} aggregate gross producing history.
    Series points: {date: "YYYY-MM", oil, gas, actual: bool}. Gross volumes.
    """
    origin_d = date.fromisoformat(origin)
    estimates: list[dict] = []

    # PDP estimate: actual history (solid) + aggregate forecast (dashed).
    # Suppressed entirely when there are no producing wells (e.g. an all-DUC/PUD
    # deal) — there's no producing base to show, so the selector shouldn't offer it.
    if producing_forecasts or actual_history.get("dates"):
        series: list[dict] = []
        for i, d in enumerate(actual_history.get("dates", [])):
            series.append({"date": d, "oil": actual_history["oil"][i],
                           "gas": actual_history["gas"][i], "actual": True})
        if producing_forecasts:
            oil_months, oil_tot = fc_engine.aggregate(
                [f["oil"] for f in producing_forecasts], horizon_months=window_months, origin=origin_d)
            _, gas_tot = fc_engine.aggregate(
                [f["gas"] for f in producing_forecasts], horizon_months=window_months, origin=origin_d)
            for i, mo in enumerate(oil_months):
                series.append({"date": f"{mo.year:04d}-{mo.month:02d}",
                               "oil": round(float(oil_tot[i]), 1), "gas": round(float(gas_tot[i]), 1),
                               "actual": False})
        estimates.append({
            "key": "pdp", "name": "PDP — producing base", "kind": "history", "series": series,
            "meta": {"analogs": None, "wells": len(producing_forecasts),
                     "radius_mi": None, "b_median": None, "basis": "own history"},
        })

    # Cohort estimate: normalized type curve (dashed only).
    if cohort_curves and non_producing_count > 0:
        oil_c, gas_c = cohort_curves["oil"], cohort_curves["gas"]
        t = np.arange(window_months, dtype=float)
        oil_rates = np.atleast_1d(fc_engine.curve_rate(oil_c, t))
        gas_rates = np.atleast_1d(fc_engine.curve_rate(gas_c, t))
        base = origin_d.year * 12 + origin_d.month - 1
        cseries = [
            {"date": f"{(base + i) // 12:04d}-{(base + i) % 12 + 1:02d}",
             "oil": round(float(oil_rates[i]), 1), "gas": round(float(gas_rates[i]), 1),
             "actual": False}
            for i in range(window_months)
        ]
        estimates.append({
            "key": "cohort", "name": "Analog cohort", "kind": "cohort", "series": cseries,
            "meta": {"analogs": (cohort_diag or {}).get("n_wells"), "wells": non_producing_count,
                     "radius_mi": (cohort_diag or {}).get("final_radius_mi"),
                     "b_median": round(oil_c.b, 2), "basis": "cohort"},
            "analog_wells": (cohort_diag or {}).get("analog_wells", []),
        })
    return estimates


def build_advanced_block(
    *, well_meta: dict, producing_forecasts: list[dict], cohort_curves: dict | None,
    cohort_diag: dict | None, non_producing_count: int, actual_history: dict,
    inputs: dict, interest: dict, effective_date: str, origin: str,
) -> dict:
    """Compose the additive `advanced` block (asset/production/econ)."""
    return {
        "asset": build_asset_block(well_meta),
        "production": {
            "now_date": origin,
            "estimates": build_production_estimates(
                producing_forecasts=producing_forecasts, cohort_curves=cohort_curves,
                cohort_diag=cohort_diag, non_producing_count=non_producing_count,
                actual_history=actual_history, origin=origin),
        },
        "econ": build_econ_block(inputs=inputs, interest=interest, effective_date=effective_date),
    }
