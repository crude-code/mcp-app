"""CSV transport for dataroom_save_extraction.

The two tall tables in an ExtractionResult (production_history,
revenue_observations) may arrive as CSV strings plus a shared `sources`
provenance legend instead of JSON arrays — the packed form is authored
mechanically in the sandbox by skills/dataroom-extract/persist_pack.py
(whose headers must match these; tests/test_persist_pack.py guards the
drift). This module rebuilds the canonical arrays, provenance included, so
what lands in platform.dataroom_extractions has exactly extraction.json's
shape — CSV exists only on the wire.
"""
import csv
import io


class TransportError(ValueError):
    """Malformed packed payload — message is row-precise so the caller can
    fix the kit and re-call."""


# Column order is the contract: header rows must match these exactly.
PRODUCTION_HEADER = [
    "well_api", "month", "oil_bbl", "gas_mcf", "water_bbl", "ngl_bbl",
    "days_on", "src", "row", "notes",
]
REVENUE_HEADER = [
    "well_api", "well_identifier", "prod_date", "check_date", "product_raw",
    "product", "volume", "volume_unit", "price", "gross_revenue", "taxes",
    "deductions", "net_revenue", "owner_decimal", "interest_type", "operator",
    "src", "row", "notes",
]

_PRODUCTION_FLOATS = {"oil_bbl", "gas_mcf", "water_bbl", "ngl_bbl", "days_on"}
_REVENUE_FLOATS = {
    "volume", "price", "gross_revenue", "taxes", "deductions", "net_revenue",
    "owner_decimal",
}

# Entity lists counted for the `stored` echo (mirrors ExtractionResult).
ENTITY_LISTS = [
    "wells", "tracts", "interests", "production_history",
    "revenue_observations", "expenses", "division_orders", "documents",
]


def _validate_sources(sources) -> dict:
    if sources is None:
        return {}
    if not isinstance(sources, dict):
        raise TransportError("sources must be an object: {id: [source_file, locator_template]}")
    clean = {}
    for key, entry in sources.items():
        if not isinstance(entry, (list, tuple)) or not entry or not isinstance(entry[0], str) or not entry[0].strip():
            raise TransportError(
                f"sources[{key!r}] must be [source_file, locator_template?] with a non-empty source_file"
            )
        template = entry[1] if len(entry) > 1 and entry[1] not in (None, "") else None
        if template is not None and not isinstance(template, str):
            raise TransportError(f"sources[{key!r}]: locator_template must be a string")
        clean[str(key)] = (entry[0], template)
    return clean


def _parse_table(text: str, *, header: list[str], float_cols: set[str],
                 sources: dict, entity: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    if [h.strip() for h in rows[0]] != header:
        raise TransportError(f"{entity}: header line must be exactly: {','.join(header)}")

    out = []
    for lineno, raw in enumerate(rows[1:], start=2):
        if not raw or all(not cell.strip() for cell in raw):
            continue
        if len(raw) != len(header):
            raise TransportError(
                f"{entity} line {lineno}: expected {len(header)} fields, got {len(raw)}"
            )
        vals = {col: (cell.strip() or None) for col, cell in zip(header, raw)}

        rec = {}
        for col in header:
            if col in ("src", "row", "notes"):
                continue
            v = vals[col]
            if v is not None and col in float_cols:
                try:
                    v = float(v)
                except ValueError:
                    raise TransportError(
                        f"{entity} line {lineno}: {col} {vals[col]!r} is not a number"
                    )
            rec[col] = v

        src = vals["src"]
        if src is None:
            raise TransportError(f"{entity} line {lineno}: src is required")
        if src not in sources:
            raise TransportError(f"{entity} line {lineno}: src {src!r} not in sources legend")
        source_file, template = sources[src]
        locator = None
        if template is not None:
            if "{n}" in template:
                if vals["row"] is None:
                    raise TransportError(
                        f"{entity} line {lineno}: row is required (locator template has {{n}})"
                    )
                locator = template.replace("{n}", vals["row"])
            else:
                locator = template
        rec["provenance"] = {
            "source_file": source_file,
            "source_locator": locator,
            "notes": vals["notes"],
        }
        out.append(rec)
    return out


def unpack_extraction(extraction: dict, *, production_csv: str = "",
                      revenue_csv: str = "", sources: dict | None = None) -> dict:
    """Expand a packed call kit into a canonical ExtractionResult dict.

    No-op when neither CSV is supplied (the plain-JSON path). Raises
    TransportError when a CSV duplicates a non-empty JSON array — one lane
    per table, never both."""
    legend = _validate_sources(sources)
    ext = dict(extraction)
    for arg, text, key, header, floats in (
        ("production_csv", production_csv, "production_history",
         PRODUCTION_HEADER, _PRODUCTION_FLOATS),
        ("revenue_csv", revenue_csv, "revenue_observations",
         REVENUE_HEADER, _REVENUE_FLOATS),
    ):
        if not text or not text.strip():
            continue
        if ext.get(key):
            raise TransportError(
                f"{key}: send rows as {arg} or as JSON in extraction, not both"
            )
        ext[key] = _parse_table(text, header=header, float_cols=floats,
                                sources=legend, entity=arg)
    return ext


def entity_counts(extraction: dict) -> dict:
    """Per-entity row counts of what will actually be stored — the `stored`
    echo the skill compares against persist_pack.py's counts."""
    return {key: len(extraction.get(key) or []) for key in ENTITY_LISTS}
