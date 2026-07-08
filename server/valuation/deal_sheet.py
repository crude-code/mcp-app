"""Pure assembly helpers for the valuation deal-sheet facts, shared by the
artifact-payload path.

No DB, no I/O. Inputs are plain dicts read from the wells/economics stages;
outputs (exec facts, per-status rows, net production series) feed
`server.valuation.artifact_payload.build_artifact_payload`.
"""
from collections import Counter, defaultdict

from server.valuation import config
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


def default_rates(rate_centers: dict) -> dict:
    """Default selection = each status's center rung. Derived from
    `config.rate_ladder(center)[1]` (the rounded middle rung) so the label is
    byte-identical to the matching `rates` entry and the cube key."""
    return {code: _fmt_rate(config.rate_ladder(center)[1]) for code, center in rate_centers.items()}


