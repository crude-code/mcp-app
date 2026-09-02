"""Engine types. Lateral length enters the model only through Claude's analog
selection (comparable laterals); the server never rescales a curve by it."""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ForecastProvenance:
    source: str                                 # "asserted"
    strategy: str | None = None                 # "asserted" | "not_asserted" (a stream Claude left out)


@dataclass(frozen=True)
class DeclineCurve:
    qi: float                                   # rate at the anchor month (units/month) — never peak-anything
    di: float                                   # nominal monthly decline at the anchor
    b: float
    terminal_di_monthly: float
    switch_month_from_peak: float               # months after the anchor (t=0) where the terminal
                                                # exponential takes over; float("inf") when it never
                                                # does. The name is also the persisted JSON key.
    stream: str                                 # "oil" | "gas"
    provenance: ForecastProvenance


@dataclass(frozen=True)
class Forecast:
    """A curve placed on the calendar: `start_date` is the month where t=0
    (the asserted anchor for a producer, the asserted online month for an
    undrilled well)."""
    curve: DeclineCurve
    start_date: date


@dataclass(frozen=True)
class WellMeta:
    api: str
    status: str
    basin: str | None
    formation: str | None
    county: str | None
    lateral_ft: float | None
    n_history_months: int
    geom_wkt: str | None = None                 # well point as WKT, for centroid math
    operator: str | None = None                 # public.wells.operator (free-text)
    well_name: str | None = None                # public.wells.well_name (display)
