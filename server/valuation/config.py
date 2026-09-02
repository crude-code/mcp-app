"""Tunable domain constants for the valuation engine.

Every economic parameter lives in the ``EconConfig`` dataclass (``ECON``
singleton below). Decline parameters (qi / di / b) are asserted by Claude per
well and are never configured here; the one forecast constant the server owns
is the terminal decline — it belongs to the calculator, not to judgment.
"""
from dataclasses import dataclass, field
from datetime import date

from dateutil.relativedelta import relativedelta


# ── The valuation config: every economic parameter, one object ───────────────
#
# Single source for the economic side of a valuation. Decline parameters are
# asserted per well through `deal_forecast_wells` and never live here; the terminal
# decline does, because the exponential tail is the calculator's own policy.
# Read it as `config.ECON.<field>`; never re-hardcode these values at a call
# site.

@dataclass(frozen=True)
class EconConfig:
    # Price deck — flat, v1 (NYMEX strip is a later slice).
    oil_price: float = 70.0          # $/bbl
    gas_price: float = 3.50          # $/MMBtu

    # Differentials off the deck.
    oil_diff: float = 0.0            # $/bbl
    gas_diff: float = 0.0            # $/MMBtu

    # Gas heat content, MMBtu per mcf. Production volumes are mcf; benchmark
    # prices (NYMEX Henry Hub / flat gas deck) are $/MMBtu — revenue must
    # convert: gas_mcf × btu × ($/MMBtu). 1.05 is a typical dry-gas heat
    # content; wet-gas areas run 1.1–1.3 (override per deal). NGL uplift and
    # shrink are out of scope — they partially offset at typical yields.
    gas_btu_factor: float = 1.05

    # Taxes / deductions (WI branch).
    tax_pct: float = 0.075           # severance/production
    gpt_pct: float = 0.05            # gathering, processing, transport

    # Operating + capital costs.
    opex_per_bbl_usd: float = 0.0
    opex_per_well_per_month_usd: float = 0.0
    capex_per_well_usd: float = 0.0  # drilling AFE, WI only

    # Cashflow horizon.
    horizon_months: int = 360        # 30 yr

    # Terminal decline: once a curve's hyperbolic decline shallows to this
    # annual rate, the calculator switches it onto an exponential tail at
    # this rate. The calculator's, never Claude's — asserted parameters are
    # {qi, di, b} only.
    terminal_di_annual: float = 0.05

    # Non-producing-well online timing FALLBACK (months from the
    # first-of-next-month anchor): a DUC is drilled awaiting completion
    # (closer); a permit is not yet spudded (further out). New forecast
    # stages carry an asserted online month (`anchor_month`) and never touch
    # these; they date only legacy stages committed before timing became an
    # asserted parameter.
    duc_months_to_first_prod: int = 18
    permit_months_to_first_prod: int = 36

    # Per-status annual discount-rate CENTERS (decimal). Each well-status stream
    # is discounted at its own cost of capital; uncertainty rises PDP → DUC → PUD.
    # The deal sheet bands each center by ``rate_spread`` into a 3-rung ladder
    # (center − spread / center / center + spread) and defaults to the center.
    # A user-supplied per-status rate overrides the center (see
    # ``resolve_rate_centers``); the spread stays fixed.
    default_rate_centers: dict[str, float] = field(default_factory=lambda: {
        "PDP": 0.15, "DUC": 0.20, "PUD": 0.25,
    })
    rate_spread: float = 0.025

    # Risked-cube flat oil reference decks ($/bbl), shown AFTER the base (strip)
    # column: the base prices off the run's path, then these flat-oil scenarios.
    # Gas is held at the run's gas path across every deck.
    deck_oil_flat: tuple[float, ...] = (70.0, 75.0, 80.0)


ECON = EconConfig()


def rate_ladder(center: float) -> tuple[float, float, float]:
    """A per-status discount ladder banded around ``center`` by ``ECON.rate_spread``:
    ``(center - spread, center, center + spread)``. Rounded to avoid IEEE-754
    subtraction artefacts (e.g. 0.15 − 0.025 = 0.12499…) that would otherwise
    break the percent-label keys (0.15 → 0.125 / 0.15 / 0.175)."""
    spread = ECON.rate_spread
    return (round(center - spread, 6), round(center, 6), round(center + spread, 6))


def rate_label(rate: float) -> str:
    """Decimal annual rate → the percent-string key the PV cube, the status
    rows' `rates` and `default_rates` all share (0.175 → '17.5'). One
    formatter so the template's selector always finds its cube cell."""
    return f"{rate * 100:g}"


def resolve_rate_centers(econ_overrides: dict | None) -> dict[str, float]:
    """Per-status discount-rate centers for a deal: a user-supplied
    ``economics_overrides.discount_rates`` map (per status) overrides the
    config default center; any status the user omits keeps its default. The
    case file is validated at the MCP boundary, so values here are trusted."""
    overrides = (econ_overrides or {}).get("discount_rates") or {}
    return {
        code: float(overrides.get(code, default))
        for code, default in ECON.default_rate_centers.items()
    }


def deck_labels(price_mode: str = "strip") -> tuple[list[str], str]:
    """Ordered cube deck labels + the base label, for a given price mode.

    The first deck is the base — the run's actual oil path: the strip
    (``"Strip"``) or, under a flat override, ``"Flat"``. The remaining decks are
    fixed flat-oil reference scenarios from ``ECON.deck_oil_flat`` (``"$70"`` …).
    Both the cube builder and the deal-sheet spec read labels from here so the
    cube keys, the ``decks`` list, and the renderer's segmented control agree.
    """
    base = "Strip" if price_mode == "strip" else "Flat"
    return [base, *(f"${int(p)}" for p in ECON.deck_oil_flat)], base


def default_deck_label(price_mode: str = "strip") -> str:
    """The cube's default deck label — the base (first) deck: the run's price path."""
    return deck_labels(price_mode)[1]


def status_code(well_status: str | None) -> str:
    """Map a ``public.wells.well_status`` to the deal sheet's PV bucket.

    PRODUCING → PDP, DUC → DUC, PERMITTED → PUD. The ingest only loads those
    three statuses; anything else (or ``None``) falls back to the producing
    bucket so a well can never silently drop out of the cube.
    """
    s = (well_status or "").strip().upper()
    if s == "DUC":
        return "DUC"
    if s == "PERMITTED":
        return "PUD"
    return "PDP"


def first_of_next_month(d: date) -> date:
    """First day of the month following ``d`` (always rolls forward, even when
    ``d`` is already a first-of-month).

    This is the shared timeline anchor: the non-producing-well online dates and
    the economics NPV origin both reference it, so a DUC dated ``+18mo`` lands
    exactly 18 months into the cash-flow timeline.
    """
    return d.replace(day=1) + relativedelta(months=1)


def planned_first_prod_date(
    status: str | None,
    *,
    as_of: date,
    months_override: dict[str, int] | None = None,
) -> date | None:
    """Assumed first-production date for a non-producing well.

    Anchored at the first of the month following ``as_of`` (the valuation
    effective date, or today). DUCs come online ``ECON.duc_months_to_first_prod``
    months out; permits ``ECON.permit_months_to_first_prod``. Any other status
    (or ``None``) returns ``None`` — the engine has no basis to date it.

    ``months_override`` is a per-deal replacement of those default deltas, keyed
    by the deal-sheet status code (``DUC`` / ``PUD``, matching ``discount_rates``):
    e.g. ``{"PUD": 1}`` brings permitted wells online one month after the anchor
    instead of 36. A status absent from the map keeps its config default. The
    case file is validated at the MCP boundary, so values here are trusted.
    """
    anchor = first_of_next_month(as_of)
    s = (status or "").strip().upper()
    ov = months_override or {}
    if s == "DUC":
        return anchor + relativedelta(months=ov.get("DUC", ECON.duc_months_to_first_prod))
    if s == "PERMITTED":
        return anchor + relativedelta(months=ov.get("PUD", ECON.permit_months_to_first_prod))
    return None


def resolve_price_inputs(econ_overrides: dict | None) -> dict:
    """The deal's economic inputs for the cashflow math, read straight from the
    case file's ``economics_overrides`` — the single, validated input surface.

    The agent supplies NONE of these (same treatment ``interest`` and
    ``discount_rates`` already get): the server reads every number here, so the
    persisted record reflects what was *ordered*, not what the agent retyped. Any
    field the user omits falls back to its ``ECON`` house default. Values are
    trusted — the case file is shape-validated at the MCP boundary.

    Returns the kwargs the schedule builder consumes:
    ``{horizon_months, oil_price, gas_price, oil_diff, gas_diff, gas_btu_factor,
    tax_pct, gpt_pct}``.
    (Costs and discount rates are resolved separately, also from the case file.)
    """
    o = econ_overrides or {}
    deck = o.get("price_deck") or {}
    return {
        "horizon_months": int(o.get("forecast_horizon", ECON.horizon_months)),
        "oil_price": float(deck.get("oil_usd_bbl", ECON.oil_price)),
        "gas_price": float(deck.get("gas_usd_mmbtu", ECON.gas_price)),
        "oil_diff": float(o.get("oil_diff", ECON.oil_diff)),
        "gas_diff": float(o.get("gas_diff", ECON.gas_diff)),
        "gas_btu_factor": float(o.get("gas_btu_factor", ECON.gas_btu_factor)),
        "tax_pct": float(o.get("tax_pct", ECON.tax_pct)),
        "gpt_pct": float(o.get("gpt_pct", ECON.gpt_pct)),
    }


def resolve_as_of(effective_date: "str | date | None", *, today: date) -> date:
    """Resolve the valuation as-of date.

    Prefers ``effective_date`` (a ``date`` or ISO-8601 string) from the case
    file's ``economics_overrides``; falls back to ``today`` when it is absent
    or unparseable. Keeping ``today`` as a caller-supplied argument leaves this
    function pure and testable.
    """
    if effective_date is None:
        return today
    if isinstance(effective_date, date):
        return effective_date
    try:
        return date.fromisoformat(str(effective_date)[:10])
    except ValueError:
        return today
