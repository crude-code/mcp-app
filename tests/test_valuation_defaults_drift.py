"""Guard: the House defaults table in tool_deal_valuation.md must match config.ECON.

The valuation tool prompt documents every house default so Claude can resolve the
assumptions grid it shows the user *before* running. If those documented numbers
drift from the engine's actual defaults (server/valuation/config.py), the grid lies
— the user confirms one set of assumptions and the engine runs another. This test
parses the machine-readable block between `<!-- cc:econ_defaults:start -->` and
`<!-- cc:econ_defaults:end -->` (the `Field` and `Raw` columns) and asserts every
documented default equals the live value on `config.ECON`.

If you change a default in config.py, update the table; if you add a field, add a
row (and an expectation here). Either way this test keeps them honest.
"""

import re
from pathlib import Path

from server.valuation import config

_PROMPT = Path(__file__).resolve().parent.parent / "prompts/outer/tool_deal_valuation.md"
_BLOCK_RE = re.compile(
    r"<!-- cc:econ_defaults:start -->\s*(.*?)\s*<!-- cc:econ_defaults:end -->",
    re.DOTALL,
)


def _expected() -> dict[str, object]:
    """The defaults the prompt's `Raw` column must reproduce, pulled live from ECON."""
    e = config.ECON
    return {
        "oil_price": e.oil_price,
        "gas_price": e.gas_price,
        "oil_diff": e.oil_diff,
        "gas_diff": e.gas_diff,
        "gas_btu_factor": e.gas_btu_factor,
        "tax_pct": e.tax_pct,
        "gpt_pct": e.gpt_pct,
        "opex_per_bbl_usd": e.opex_per_bbl_usd,
        "opex_per_well_per_month_usd": e.opex_per_well_per_month_usd,
        "capex_per_well_usd": e.capex_per_well_usd,
        "horizon_months": float(e.horizon_months),
        "terminal_di_annual": e.terminal_di_annual,
        "discount_rate_pdp": e.default_rate_centers["PDP"],
        "discount_rate_duc": e.default_rate_centers["DUC"],
        "discount_rate_pud": e.default_rate_centers["PUD"],
        "rate_spread": e.rate_spread,
        "deck_oil_flat": tuple(float(x) for x in e.deck_oil_flat),
    }


def _parse_block() -> dict[str, str]:
    """{field_token: raw_string} from the doc's defaults table."""
    text = _PROMPT.read_text()
    match = _BLOCK_RE.search(text)
    assert match, (
        "missing <!-- cc:econ_defaults:start --> ... <!-- cc:econ_defaults:end --> "
        "block in prompts/outer/tool_deal_valuation.md"
    )
    rows: dict[str, str] = {}
    for line in match.group(1).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        field, _label, _display, raw = cells
        if field in ("Field", "-------") or set(field) <= {"-"}:
            continue
        rows[field] = raw
    return rows


def _as_value(raw: str) -> object:
    """Parse a `Raw` cell: a comma list → tuple of floats, else a float."""
    if "," in raw:
        return tuple(float(x) for x in raw.split(","))
    return float(raw)


def test_documented_defaults_match_config():
    documented = _parse_block()
    expected = _expected()

    assert set(documented) == set(expected), (
        "House defaults table fields do not match the expected set:\n"
        f"  in prompt: {sorted(documented)}\n"
        f"  expected:  {sorted(expected)}"
    )

    mismatches = []
    for field, exp in expected.items():
        got = _as_value(documented[field])
        if isinstance(exp, tuple):
            ok = got == exp
        else:
            ok = abs(float(got) - float(exp)) < 1e-9
        if not ok:
            mismatches.append(f"  {field}: prompt={got!r} config={exp!r}")
    assert not mismatches, "House defaults drifted from config.ECON:\n" + "\n".join(mismatches)
