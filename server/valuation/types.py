"""Engine types. NO lateral_norm_ft, NO lateral_scale — analog selection
(Claude's judgment: comparable laterals in the cohort) is the only place
lateral enters the model; the server never rescales."""
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ForecastProvenance:
    source: str                                 # "fit" | "percentile" | "blend" | "cohort"
    fit_n_input_months: int = 0
    component_curves: tuple["ForecastProvenance", ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)
    strategy: str | None = None                 # "history" | "history_own_b" | "thin_blend" |
                                                # "climbing" | "pure_analog" | "zero_stream"


@dataclass(frozen=True)
class DeclineCurve:
    qi_peak: float
    di: float
    b: float
    terminal_di_monthly: float
    switch_month_from_peak: float            # float("inf") when no terminal switch
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
