"""Deal-terms validation for `deal_valuation`.

`parse_run_params` validates the `params` object the tool receives and
returns a typed CaseFile the orchestrator can read without re-checking
shapes: interest type + blanket interest (with optional per-well `by_api`
overrides), the asset list, and the pinned `economics_overrides` schema.
"""
from dataclasses import dataclass, field


class CaseFileError(ValueError):
    """Raised when the case file fails schema validation."""


# Hard cap on deal size. The economics schedule holds 4 full deck-scenarios of
# (wells × 360 months × 11 columns) float arrays; 500 wells ≈ 60 MB transient,
# which is the most this box should spend on one request.
MAX_ASSET_WELLS = 500


@dataclass
class CaseFile:
    interest_type: str                              # "wi" | "minerals"
    interest: dict                                  # {wi_pct, nri_pct} or {decimal}
    asset_list: dict = field(default_factory=dict)  # optional {well_apis: [...]} — a cross-check
    economics_overrides: dict = field(default_factory=dict)


_DISCOUNT_STATUSES = {"PDP", "DUC", "PUD"}

# The complete, pinned set of economic-override keys. economics_overrides is the
# single input surface for deal economics — the server reads every number from
# here (the agent supplies none), so the schema is locked: an unknown key is a
# typo or a fabricated field, and we reject it rather than silently ignore it.
_ALLOWED_ECON_OVERRIDES = {
    "effective_date", "price_deck", "oil_diff", "gas_diff", "gas_btu_factor",
    "forecast_horizon", "tax_pct", "gpt_pct", "discount_rates",
    "opex_per_bbl_usd", "opex_per_well_per_month_usd", "capex_per_well_usd",
}


def _check_fraction(v, label: str) -> None:
    """Raise unless ``v`` is a real number in [0, 1] (bools rejected)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0.0 <= v <= 1.0):
        raise CaseFileError(f"{label} must be in [0, 1], got {v!r}")


def _check_money(v, label: str, *, allow_negative: bool = False) -> None:
    """Raise unless ``v`` is a real number (bools rejected); non-negative by default."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise CaseFileError(f"{label} must be a number, got {v!r}")
    if not allow_negative and v < 0:
        raise CaseFileError(f"{label} must be non-negative, got {v!r}")


def _validate_deal_terms(body: dict) -> dict:
    """Validate the deal terms: interest_type, interest (incl. by_api),
    asset_list, economics_overrides. Raises CaseFileError. Returns the
    validated/normalized fields."""
    if not isinstance(body, dict):
        raise CaseFileError(f"case file must be an object, got {type(body).__name__}")

    interest_type = body.get("interest_type")
    if interest_type not in ("wi", "minerals"):
        raise CaseFileError(
            f"interest_type must be 'wi' or 'minerals', got {interest_type!r}"
        )

    interest = body.get("interest")
    if not isinstance(interest, dict):
        raise CaseFileError("interest must be an object")
    if interest_type == "wi":
        for k in ("wi_pct", "nri_pct"):
            if k not in interest:
                raise CaseFileError(f"interest.{k} is required for interest_type='wi'")
            _check_fraction(interest[k], f"interest.{k}")
    else:  # minerals
        if "decimal" not in interest:
            raise CaseFileError("interest.decimal is required for interest_type='minerals'")
        _check_fraction(interest["decimal"], "interest.decimal")

    # Optional per-well overrides: blanket above is the default for any well
    # not listed here. WI entries are {wi_pct, nri_pct}; minerals entries are a
    # bare decimal — mirroring the blanket shape for that interest type.
    by_api = interest.get("by_api")
    if by_api is not None:
        if not isinstance(by_api, dict):
            raise CaseFileError("interest.by_api must be an object keyed by well API")
        for api, ov in by_api.items():
            if interest_type == "wi":
                if not isinstance(ov, dict):
                    raise CaseFileError(f"interest.by_api[{api!r}] must be an object with wi_pct and nri_pct")
                for k in ("wi_pct", "nri_pct"):
                    if k not in ov:
                        raise CaseFileError(f"interest.by_api[{api!r}].{k} is required for interest_type='wi'")
                    _check_fraction(ov[k], f"interest.by_api[{api!r}].{k}")
            else:  # minerals
                if isinstance(ov, bool) or not isinstance(ov, (int, float)):
                    raise CaseFileError(f"interest.by_api[{api!r}] must be a decimal number for interest_type='minerals'")
                _check_fraction(ov, f"interest.by_api[{api!r}]")

    # asset_list is optional. The wells a valuation covers are whatever
    # deal_forecast_wells committed to the run; when Claude declares the list
    # it expects, the orchestrator refuses a run that holds different wells —
    # the guard against valuing the wrong run_id. Nothing else reads it.
    asset_list = body.get("asset_list") or {}
    if not isinstance(asset_list, dict):
        raise CaseFileError("asset_list must be an object like {'well_apis': [...]}")
    if set(asset_list) - {"well_apis"}:
        raise CaseFileError(
            "asset_list takes only well_apis — the run's wells come from "
            "deal_forecast_wells, there is nothing to filter server-side"
        )
    if "well_apis" in asset_list:
        apis = asset_list["well_apis"]
        if not isinstance(apis, list) or not all(isinstance(a, str) and a.strip() for a in apis):
            raise CaseFileError("asset_list.well_apis must be a list of non-empty strings")
        deduped = list(dict.fromkeys(apis))
        if len(deduped) > MAX_ASSET_WELLS:
            raise CaseFileError(
                f"asset_list.well_apis has {len(deduped)} wells; at most {MAX_ASSET_WELLS} "
                "per valuation — split the deal"
            )
        asset_list = {"well_apis": deduped}

    economics_overrides = body.get("economics_overrides", {}) or {}
    if not isinstance(economics_overrides, dict):
        raise CaseFileError("economics_overrides must be an object")

    unknown = set(economics_overrides) - _ALLOWED_ECON_OVERRIDES
    if unknown:
        raise CaseFileError(
            f"economics_overrides has unknown key(s): {sorted(unknown)}; "
            f"allowed: {sorted(_ALLOWED_ECON_OVERRIDES)}"
        )

    dr = economics_overrides.get("discount_rates")
    if dr is not None:
        if not isinstance(dr, dict):
            raise CaseFileError(
                "economics_overrides.discount_rates must be an object keyed by "
                "well status (PDP/DUC/PUD), e.g. {'PUD': 0.25}"
            )
        unknown = set(dr) - _DISCOUNT_STATUSES
        if unknown:
            raise CaseFileError(
                f"economics_overrides.discount_rates has unknown status key(s): {sorted(unknown)}"
            )
        for code, rate in dr.items():
            # open interval: a 0% or 100% discount rate is nonsensical (unlike
            # the blanket WI/NRI fractions, which _check_fraction allows at 0/1).
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not (0.0 < rate < 1.0):
                raise CaseFileError(
                    f"economics_overrides.discount_rates[{code!r}] must be a number in (0, 1), got {rate!r}"
                )

    # Price deck — the benchmark prices the deal is run against. Default (absent
    # or type 'strip') is the live NYMEX strip; 'flat' is an opt-in constant deck.
    pd = economics_overrides.get("price_deck")
    if pd is not None:
        if not isinstance(pd, dict):
            raise CaseFileError(
                "economics_overrides.price_deck must be an object, e.g. "
                "{'type': 'strip'} or {'type': 'flat', 'oil_usd_bbl': 80, 'gas_usd_mmbtu': 3.5}"
            )
        ptype = pd.get("type", "strip")
        if ptype not in ("strip", "flat"):
            raise CaseFileError(
                f"economics_overrides.price_deck.type must be 'strip' or 'flat', got {ptype!r}"
            )
        if ptype == "strip":
            # The strip carries its own prices — flat scalars are meaningless here.
            unknown = set(pd) - {"type"}
            if unknown:
                raise CaseFileError(
                    f"economics_overrides.price_deck type 'strip' takes no price keys; "
                    f"remove {sorted(unknown)}"
                )
        else:
            unknown = set(pd) - {"type", "oil_usd_bbl", "gas_usd_mmbtu"}
            if unknown:
                raise CaseFileError(f"economics_overrides.price_deck has unknown key(s): {sorted(unknown)}")
            if "oil_usd_bbl" in pd:
                _check_money(pd["oil_usd_bbl"], "economics_overrides.price_deck.oil_usd_bbl")
            if "gas_usd_mmbtu" in pd:
                _check_money(pd["gas_usd_mmbtu"], "economics_overrides.price_deck.gas_usd_mmbtu")

    # Differentials — dollars per unit taken OFF the benchmark deck (location /
    # quality basis): realized = deck − diff. Positive = sells below benchmark;
    # negative = a premium. Flat fields, named to match the engine's params.
    for k in ("oil_diff", "gas_diff"):
        v = economics_overrides.get(k)
        if v is not None:
            _check_money(v, f"economics_overrides.{k}", allow_negative=True)

    # Gas heat content — MMBtu per mcf, converting mcf volumes to the $/MMBtu
    # benchmark. Physically plausible band only (dry ~1.0, rich wet gas <2.0).
    btu = economics_overrides.get("gas_btu_factor")
    if btu is not None and (isinstance(btu, bool) or not isinstance(btu, (int, float))
                            or not (0.5 <= btu <= 2.0)):
        raise CaseFileError(
            f"economics_overrides.gas_btu_factor must be a number in [0.5, 2.0] "
            f"(MMBtu per mcf), got {btu!r}"
        )

    # Forecast horizon — months of cashflow projected.
    fh = economics_overrides.get("forecast_horizon")
    if fh is not None and (isinstance(fh, bool) or not isinstance(fh, int) or not (1 <= fh <= 600)):
        raise CaseFileError(
            f"economics_overrides.forecast_horizon must be an integer 1–600 (months), got {fh!r}"
        )

    # Tax / GPT — fractions in [0, 1).
    for k in ("tax_pct", "gpt_pct"):
        v = economics_overrides.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not (0.0 <= v < 1.0)):
            raise CaseFileError(f"economics_overrides.{k} must be a number in [0, 1), got {v!r}")

    # Per-unit / per-well costs (WI only) — non-negative dollars.
    for k in ("opex_per_bbl_usd", "opex_per_well_per_month_usd", "capex_per_well_usd"):
        v = economics_overrides.get(k)
        if v is not None:
            _check_money(v, f"economics_overrides.{k}")

    # Effective date — ISO-8601 date string (the valuation as-of date).
    ed = economics_overrides.get("effective_date")
    if ed is not None:
        from datetime import date as _date
        try:
            _date.fromisoformat(str(ed)[:10])
        except ValueError:
            raise CaseFileError(
                f"economics_overrides.effective_date must be an ISO-8601 date (YYYY-MM-DD), got {ed!r}"
            )

    return {
        "interest_type": interest_type,
        "interest": interest,
        "asset_list": asset_list,
        "economics_overrides": economics_overrides,
    }


def parse_run_params(params: dict) -> CaseFile:
    """Validate deal_valuation's ``params`` (interest + asset_list +
    economics_overrides). Raises CaseFileError on bad input."""
    terms = _validate_deal_terms(params)
    return CaseFile(
        interest_type=terms["interest_type"],
        interest=terms["interest"],
        asset_list=terms["asset_list"],
        economics_overrides=terms["economics_overrides"],
    )
