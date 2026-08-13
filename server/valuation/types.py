"""Engine types. NO lateral_norm_ft, NO lateral_scale — offset selection
(Claude's judgment: comparable laterals) is the only place lateral enters the
model; the server never rescales."""
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ForecastProvenance:
    source: str                                 # "asserted" | legacy: "fit"/"percentile"/"blend"/"cohort"
    notes: tuple[str, ...] = field(default_factory=tuple)
    strategy: str | None = None                 # "asserted" | "not_asserted" | legacy fit-era values


@dataclass(frozen=True)
class DeclineCurve:
    qi: float                                   # rate at the anchor month (units/month) — never peak-anything
    di: float                                   # nominal monthly decline at the anchor
    b: float
    terminal_di_monthly: float
    switch_month_from_peak: float               # float("inf") when no terminal switch. Asserted
                                                # curves anchor at t=0 (peak == anchor); the name
                                                # survives from the fit era where t=0 was the peak.
    stream: str                                 # "oil" | "gas"
    provenance: ForecastProvenance


@dataclass(frozen=True)
class Forecast:
    curve: DeclineCurve
    peak_date: date
    start_date: date
    provenance: ForecastProvenance


@dataclass(frozen=True)
class WellMeta:
    api: str
    status: str
    basin: str | None
    formation: str | None
    county: str | None
    lateral_ft: float | None
    spud_date: date | None
    completion_date: date | None
    first_prod_date: date | None
    last_prod_date: date | None
    n_history_months: int
    planned_first_prod_date: date | None        # spud_date + offset if first_prod_date is None
    geom_wkt: str | None = None                 # well point as WKT, for centroid math
    operator: str | None = None                 # public.wells.operator (free-text)
    well_name: str | None = None                # public.wells.well_name (display)
