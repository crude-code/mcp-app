"""Pydantic schema for dataroom extraction — the authoritative output contract.

Your job is to fill an `ExtractionResult` and write it to `extraction.json`.

Tight typed entities. There is NO `extras` dict — anything that doesn't fit a
typed field goes in `extraction_notes` (free-form prose) or is dropped. Do NOT
invent fields and do NOT subclass entities.

`RevenuePoint` carries SUMMED `taxes` and `deductions` (not per-category fields)
because operator line-item labels are too inconsistent across check stubs.
`ExpensePoint` is the home for LOE / opex / capex — it maps to the valuation's
economics_overrides. `Well.public_well_object` is left null in this sandbox
(no database access here).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    """Source attribution carried by every extracted record. Required."""

    model_config = ConfigDict(extra="forbid")

    source_file: str = Field(
        ...,
        description="Relative path within the dataroom root (e.g. 'Check Stubs/2024_ckstb.pdf').",
    )
    source_locator: str | None = Field(
        None,
        description='Location within the file — e.g. "sheet:Wells;row:3" (Excel, 1-based, header=row 1) or "page:2" (PDF).',
    )
    notes: str | None = Field(
        None,
        description="Reasoning when the value was inferred rather than literally read.",
    )


class EntityBase(BaseModel):
    """Common base: mandates provenance, forbids unknown fields."""

    model_config = ConfigDict(extra="forbid")

    provenance: Provenance


class Deal(EntityBase):
    title: str | None = None
    process_type: str | None = None  # negotiated_sale / auction / unknown
    category: str | None = None      # WI / RI / MI / NPRI / ORRI / MIXED
    seller: str | None = None
    operator: str | None = None      # primary operator if singular
    operators: str | None = None     # comma-joined when multiple
    broker: str | None = None        # M&A advisor
    state: str | None = None
    county: str | None = None
    basin: str | None = None
    formation: str | None = None
    field: str | None = None
    location_text: str | None = None
    asset_type: str | None = None    # PDP / PUD / DUC / mineral / mixed
    well_count: int | None = None
    gross_acres: float | None = None
    net_acres: float | None = None
    effective_date: str | None = None
    bid_due_date: str | None = None
    closing_date: str | None = None
    summary: str | None = None
    pv10_mid_mm: float | None = None       # seller-stated PV10 ($MM), if quoted
    current_net_boed: float | None = None


class Well(EntityBase):
    api: str | None = None           # 12-char SS-CCC-WWWWW; null when only a name is given
    name: str | None = None
    operator: str | None = None
    county: str | None = None
    state: str | None = None
    basin: str | None = None
    field: str | None = None
    formation: str | None = None
    well_type: str | None = None     # economic category: PDP / PUD / DUC / SI / PA
    operator_status_raw: str | None = None
    trajectory: str | None = None    # HORIZONTAL / VERTICAL / DIRECTIONAL
    lateral_length_ft: float | None = None
    tvd_ft: float | None = None
    md_ft: float | None = None
    first_prod_date: str | None = None
    public_well_object: dict[str, Any] | None = None  # left null in this sandbox (no DB)


class Tract(EntityBase):
    name: str | None = None
    legal_description: str | None = None
    county: str | None = None
    state: str | None = None
    gross_acres: float | None = None
    nma: float | None = None
    nra: float | None = None
    royalty_decimal: float | None = None
    survey: str | None = None
    abstract: str | None = None
    section: str | None = None
    block: str | None = None
    township: str | None = None
    range: str | None = None
    operator: str | None = None
    lessor: str | None = None
    lessee: str | None = None


class Interest(EntityBase):
    well_api: str | None = None
    tract_name: str | None = None
    interest_type: str | None = None  # WI / MI / NPRI / ORRI / RI
    wi_decimal: float | None = None
    nri_decimal: float | None = None
    ri_decimal: float | None = None
    npri_decimal: float | None = None
    orri_decimal: float | None = None
    lessor: str | None = None
    lessee: str | None = None
    owner: str | None = None


class ProductionPoint(EntityBase):
    well_api: str | None = None
    month: str | None = None         # YYYY-MM-01
    oil_bbl: float | None = None
    gas_mcf: float | None = None
    water_bbl: float | None = None
    ngl_bbl: float | None = None
    days_on: float | None = None


class RevenuePoint(EntityBase):
    """One row per (well, prod_date, product, check_date).

    Line-item taxes and deducts are SUMMED into `taxes` and `deductions`.
    Operators report categories inconsistently; the sanity check on each row is
    `gross_revenue - taxes - deductions ~= net_revenue`.
    """
    well_api: str | None = None
    well_identifier: str | None = None
    prod_date: str | None = None
    check_date: str | None = None
    product_raw: str | None = None
    product: str | None = None       # oil / gas / ngl / condensate
    volume: float | None = None
    volume_unit: str | None = None   # bbl / mcf / gal
    price: float | None = None       # $ per volume_unit (realized)
    gross_revenue: float | None = None
    taxes: float | None = None       # summed
    deductions: float | None = None  # summed
    net_revenue: float | None = None
    owner_decimal: float | None = None
    interest_type: str | None = None  # R / W / ORRI / NPRI
    operator: str | None = None       # payor


class ExpensePoint(EntityBase):
    """Operating-cost or capital observation — the home for LOE/opex/capex.

    Sourced from an LOS (lease operating statement), AFE, or cash-flow model.
    Feeds the valuation's economics_overrides. Fill whichever rate field the
    document actually states; leave the others null.
    """
    well_api: str | None = None
    scope: str | None = None             # well / lease / deal
    category: str | None = None          # opex / capex / workover / facility / water / other
    label_raw: str | None = None         # operator's line-item label, verbatim
    period: str | None = None            # YYYY-MM if a single month
    amount_usd: float | None = None      # total $ for the period, if stated
    opex_per_bbl_usd: float | None = None
    opex_per_well_per_month_usd: float | None = None
    capex_per_well_usd: float | None = None       # drilling/completion AFE per well
    notes: str | None = None


class DivisionOrder(EntityBase):
    well_api: str | None = None
    property_name: str | None = None
    effective_date: str | None = None
    grantor: str | None = None
    grantee: str | None = None
    decimal: float | None = None
    instrument_text: str | None = None


class Document(EntityBase):
    path: str
    category: str | None = None     # engineering / title / financial / legal / regulatory / marketing / other
    file_type: str | None = None
    size_bytes: int | None = None
    summary: str | None = None


class ExtractionResult(BaseModel):
    """Top-level container — every entity list is optional. Write this to extraction.json."""

    model_config = ConfigDict(extra="forbid")

    deal: Deal | None = None
    wells: list[Well] = []
    tracts: list[Tract] = []
    interests: list[Interest] = []
    production_history: list[ProductionPoint] = []
    revenue_observations: list[RevenuePoint] = []
    expenses: list[ExpensePoint] = []
    division_orders: list[DivisionOrder] = []
    documents: list[Document] = []
    flags: list[str] = []            # read-before-bidding caveats: one short sentence
    #   each (a payout reversion, an ownership mismatch, an unmodeled term...).
    #   These lead the viewer's cover page; keep them load-bearing and few.
    extraction_notes: str | None = None  # the longer data-quality prose record
