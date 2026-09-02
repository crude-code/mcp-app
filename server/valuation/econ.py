"""Revenue → cashflow → NPV. Two branches: WI (revenue at NRI, severance on that
NRI share, GPT deducts + capex + opex on the WI share) vs minerals (no
capex/opex/GPT, decimal × revenue × (1 − tax)).

Tax incidence: severance is borne pro-rata to REVENUE interest — the WI owner
pays tax on the NRI share it receives, minerals on its decimal — so summed
across a well's cap table the engine collects exactly tax × gross, once. GPT is
the cost-free-royalty convention: royalty/minerals bear no deducts, so the
working interest absorbs the full deduct burden pro-rata to WI."""
from typing import Literal
import numpy as np

from server.valuation import config


def resolve_well_interest(
    interest_type: Literal["wi", "minerals"],
    api: str,
    *,
    wi_pct: float | None = None,
    nri_pct: float | None = None,
    decimal: float | None = None,
    by_api: dict | None = None,
) -> dict:
    """Effective interest for one well: a ``by_api`` entry overrides the blanket.

    Returns ``{"wi_pct", "nri_pct"}`` for WI or ``{"decimal"}`` for minerals —
    the same scalar shape the cashflow functions consume, so the caller can
    splat it per well inside the schedule loop. Wells absent from ``by_api``
    (or when ``by_api`` is None) take the blanket values.
    """
    override = (by_api or {}).get(api)
    if interest_type == "wi":
        if override is not None:
            return {"wi_pct": override["wi_pct"], "nri_pct": override["nri_pct"]}
        return {"wi_pct": wi_pct, "nri_pct": nri_pct}
    if override is not None:
        return {"decimal": override}
    return {"decimal": decimal}


def compute_gross_revenue(
    oil_bbl: np.ndarray,
    gas_mcf: np.ndarray,
    *,
    oil_price: float,
    gas_price: float,
    oil_diff: float = config.ECON.oil_diff,
    gas_diff: float = config.ECON.gas_diff,
    gas_btu_factor: float = config.ECON.gas_btu_factor,
) -> np.ndarray:
    """Gross monthly revenue at the wellhead.

    Oil: bbl × ($/bbl − diff). Gas: mcf × BTU factor × ($/MMBtu − diff) — the
    benchmark (Henry Hub / flat deck) and the differential are per MMBtu, so
    volumes convert via ``gas_btu_factor`` (MMBtu per mcf)."""
    return (oil_bbl * (oil_price - oil_diff)
            + gas_mcf * gas_btu_factor * (gas_price - gas_diff))


def cashflow_components(
    *,
    gross_rev: np.ndarray,
    interest_type: Literal["wi", "minerals"],
    capex_per_month: np.ndarray | None = None,
    opex_per_month: np.ndarray | None = None,
    tax_pct: float = config.ECON.tax_pct,
    gpt_pct: float = config.ECON.gpt_pct,
    # WI fields
    wi_pct: float | None = None,
    nri_pct: float | None = None,
    # Mineral fields
    decimal: float | None = None,
) -> dict[str, np.ndarray]:
    """Monthly cashflow broken into its audit-trail line items.

    Returns ``{gross_rev, net_rev, sev_tax, gpt, capex, opex, net_cashflow}`` —
    each a per-month vector — where
    ``net_cashflow = net_rev − sev_tax − gpt − capex − opex``. WI takes revenue
    at NRI, pays severance on that NRI share (tax follows revenue interest),
    and bears GPT/capex/opex on its working-interest share (GPT: cost-free
    royalty — the WI absorbs the deduct burden); minerals takes ``decimal`` of
    revenue net of severance tax only (no GPT/capex/opex)."""
    n = len(gross_rev)
    capex = capex_per_month if capex_per_month is not None else np.zeros(n)
    opex = opex_per_month if opex_per_month is not None else np.zeros(n)

    if interest_type == "wi":
        if wi_pct is None or nri_pct is None:
            raise ValueError("wi_pct and nri_pct required for interest_type='wi'")
        net_rev = gross_rev * nri_pct
        # Severance follows the revenue interest: tax on the NRI share the WI
        # owner actually receives (matching the minerals branch, so cap-table
        # severance sums to exactly tax × gross). GPT stays on the WI share —
        # cost-free-royalty convention.
        sev_tax = tax_pct * gross_rev * nri_pct
        gpt = gpt_pct * gross_rev * wi_pct
    elif interest_type == "minerals":
        if decimal is None:
            raise ValueError("decimal required for interest_type='minerals'")
        # Minerals owners bear no GPT/capex/opex.
        net_rev = gross_rev * decimal
        sev_tax = tax_pct * gross_rev * decimal
        gpt = np.zeros(n)
        capex = np.zeros(n)
        opex = np.zeros(n)
    else:
        raise ValueError(f"unknown interest_type: {interest_type!r}")

    net_cashflow = net_rev - sev_tax - gpt - capex - opex
    return {
        "gross_rev": gross_rev, "net_rev": net_rev, "sev_tax": sev_tax,
        "gpt": gpt, "capex": capex, "opex": opex, "net_cashflow": net_cashflow,
    }


def npv(cashflow: np.ndarray, *, annual_rate: float) -> float:
    """Net present value of a monthly cashflow vector at a discrete annual rate,
    compounded monthly. Uses ordinary-annuity convention: each cashflow is
    collected at end of period (t = 1..n, not 0..n-1). This is the standard
    for monthly E&P production cashflows where revenue accrues over the month
    and is received at month-end."""
    if annual_rate == 0.0:
        return float(cashflow.sum())
    monthly = annual_rate / 12.0
    t = np.arange(1, len(cashflow) + 1, dtype=float)
    discount = 1.0 / np.power(1.0 + monthly, t)
    return float((cashflow * discount).sum())
