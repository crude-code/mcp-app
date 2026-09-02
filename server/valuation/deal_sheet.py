"""Pure assembly helpers for the valuation deal-sheet facts, shared by the
artifact-payload path.

No DB, no I/O. Inputs are plain dicts read from the wells/economics stages;
outputs (exec facts, per-status rows, default rates) feed
`server.valuation.artifact_payload.build_artifact_payload`.
"""
from collections import Counter, defaultdict

from server.valuation import config
from server.valuation.econ import resolve_well_interest

# Display order + labels/tags for the three status buckets. This display
# metadata feeds the artifact payload; colors live in the deal-sheet template.
# Online timing is asserted per well (deal_forecast_wells' anchor_month), so
# the tag is the bucket code, never a blanket "+N months".
_STATUS_DISPLAY = [
    {"code": "PDP", "label": "Producing", "tag": "(PDP)"},
    {"code": "DUC", "label": "DUC", "tag": "(DUC)"},
    {"code": "PUD", "label": "Permitted", "tag": "(PUD)"},
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
    """Compact one-liner that stays readable on multi-basin packages: modal
    basin +N (like _modal_operator), top-2 formations +N."""
    basins = Counter(m.get("basin") for m in well_meta.values() if m.get("basin"))
    form_counts = Counter(m.get("formation") for m in well_meta.values() if m.get("formation"))
    basin = "—"
    if basins:
        basin = _titlecase(basins.most_common(1)[0][0])
        if len(basins) > 1:
            basin = f"{basin} +{len(basins) - 1}"
    forms = [_titlecase(f) for f, _ in form_counts.most_common(2)]
    if len(form_counts) > 2:
        forms.append(f"+{len(form_counts) - 2}")
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
            "rates": [config.rate_label(r) for r in config.rate_ladder(rate_centers[code])],
        })
    return facts, statuses


def default_rates(rate_centers: dict) -> dict:
    """Default selection = each status's center rung. Derived from
    `config.rate_ladder(center)[1]` (the rounded middle rung) so the label is
    byte-identical to the matching `rates` entry and the cube key."""
    return {code: config.rate_label(config.rate_ladder(center)[1]) for code, center in rate_centers.items()}


