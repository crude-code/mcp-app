"""Deterministic ARIES database triage (bundled with the aries-explorer skill).

Opens a Microsoft Access .accdb/.mdb (an ARIES reserves & economics
database), inventories every table, and dumps the load-bearing small tables
to CSV under `_aries/` so the model reads structured text instead of a
binary. Huge computed/history tables (AC_PRODUCT, AC_DAILY, AC_MONTHLY,
AC_DETAIL) are never dumped: AC_PRODUCT is streamed into per-property
coverage stats, the rest get row counts only.

Reader backends, tried in order:
  1. mdb-tools binaries (`mdb-tables` / `mdb-export`) when on PATH
  2. the pure-Python `access_parser` package (`pip install access_parser`)
No working backend -> exits nonzero with the message to relay to the user.

Usage:
  python3 aries_triage.py <database.accdb> [--out _aries]

Writes:
  _aries/manifest.json              db info, backend, every table + row count
  _aries/triage.md                  readable inventory summary
  _aries/tables/<NAME>.csv          full dump of each core table (headers
                                    uppercased; values verbatim)
  _aries/production_coverage.json   per-PROPNUM stats streamed from AC_PRODUCT
"""

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Small, load-bearing tables: dumped in full (see ARIES.md for what each is).
CORE_TABLES = [
    "AC_PROPERTY", "AC_ECONOMIC", "AC_SCENARIO", "ARLOOKUP", "AC_FCST",
    "AC_OWNER", "AC_SETUP", "AC_SETUPDATA", "ARSYSTBL", "PROJECT",
    "PROJLIST", "DBSLIST", "TBLSETS", "ARENDDATE", "AR_SIDEFILE",
    "AC_ONELINE", "AC_ECOSUM", "AC_NOTE", "ECOPHASE", "ECOSTRM",
    "ARIESSCHEMAVERSION",
]
# Potentially huge: aggregate, never dump.
COVERAGE_TABLE = "AC_PRODUCT"          # streamed into per-property stats
COUNT_ONLY_TABLES = ["AC_DAILY", "AC_MONTHLY", "AC_DETAIL"]
DUMP_ROW_CAP = 250_000  # a "core" table bigger than this is truncated, loudly


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def to_month(value) -> str | None:
    """Lenient date -> 'YYYY-MM'. Handles datetimes, 'YYYY-MM-DD...',
    'MM/DD/YY[YY]...', and 'MM/YYYY'. Unparseable -> None (never guess)."""
    if value is None:
        return None
    if hasattr(value, "year") and hasattr(value, "month"):
        return f"{value.year:04d}-{value.month:02d}"
    s = str(value).strip().strip('"')
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        mo, yr = int(m.group(1)), int(m.group(3))
        yr = yr + (2000 if yr < 50 else 1900) if yr < 100 else yr
        return f"{yr:04d}-{mo:02d}"
    m = re.match(r"^(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}"
    return None


def to_float(value) -> float:
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


# ── backends ─────────────────────────────────────────────────────────────────
# Both yield rows as dicts keyed by UPPERCASED column name, values as strings
# (or whatever the reader returns; the CSV writer stringifies).

class MdbToolsBackend:
    name = "mdb-tools"

    def __init__(self, db: Path):
        self.db = db

    def list_tables(self) -> list[str]:
        out = subprocess.check_output(["mdb-tables", "-1", str(self.db)], text=True)
        return [t for t in out.splitlines() if t.strip()]

    def iter_rows(self, table: str):
        proc = subprocess.Popen(
            ["mdb-export", "-D", "%Y-%m-%d %H:%M:%S", str(self.db), table],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            reader = csv.reader(proc.stdout)
            header = next(reader, None)
            if header is None:
                return
            header = [h.strip().upper() for h in header]
            for row in reader:
                yield dict(zip(header, row))
        finally:
            proc.stdout.close()
            proc.wait()


class AccessParserBackend:
    name = "access_parser"

    def __init__(self, db: Path):
        from access_parser import AccessParser  # noqa: import checked by resolve
        self.parser = AccessParser(str(db))

    def list_tables(self) -> list[str]:
        # Skip Access internals mdb-tools also hides: MSys*, deleted (~*),
        # and complex-column stores (f_<32 hex>_Data — mixed case in the wild).
        return [t for t in self.parser.catalog
                if not t.startswith("MSys") and not t.startswith("~")
                and not re.match(r"^F_[0-9A-F]{32}_", t, re.I)]

    def iter_rows(self, table: str):
        data = self.parser.parse_table(table)  # {column: [values]}
        if not data:
            return
        cols = list(data)
        n = max((len(v) for v in data.values()), default=0)
        upper = [c.strip().upper() for c in cols]
        for i in range(n):
            yield {u: (data[c][i] if i < len(data[c]) else None)
                   for u, c in zip(upper, cols)}


def resolve_backend(db: Path):
    if shutil.which("mdb-tables") and shutil.which("mdb-export"):
        return MdbToolsBackend(db)
    try:
        import access_parser  # noqa: F401
    except ImportError:
        sys.exit(
            "No reader backend for the Access binary: neither mdb-tools "
            "(mdb-tables/mdb-export) nor the access_parser Python package is "
            "available.\nTry: pip install access_parser\nIf that is not "
            "possible in this environment, the database cannot be read here — "
            "say so honestly and ask the user for CSV/Excel exports instead.")
    return AccessParserBackend(db)


# ── triage ───────────────────────────────────────────────────────────────────

def dump_table(backend, table: str, out_csv: Path) -> tuple[int, bool]:
    """Dump one table to CSV. Returns (rows_written, truncated)."""
    rows = 0
    truncated = False
    writer = None
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        for row in backend.iter_rows(table):
            if writer is None:
                writer = csv.DictWriter(f, fieldnames=list(row))
                writer.writeheader()
            if rows >= DUMP_ROW_CAP:
                truncated = True
                break
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
            rows += 1
    if writer is None:  # empty table -> no header known; drop the empty file
        out_csv.unlink(missing_ok=True)
    return rows, truncated


def count_rows(backend, table: str) -> int:
    return sum(1 for _ in backend.iter_rows(table))


def production_coverage(backend, out_json: Path) -> dict:
    """Stream AC_PRODUCT into per-property coverage stats (never dumped)."""
    cov: dict = {}
    rows = 0
    for row in backend.iter_rows(COVERAGE_TABLE):
        rows += 1
        prop = str(row.get("PROPNUM") or "").strip()
        month = to_month(row.get("P_DATE"))
        if not prop:
            continue
        c = cov.setdefault(prop, {"months": set(), "cum_oil": 0.0,
                                  "cum_gas": 0.0, "cum_water": 0.0})
        if month:
            c["months"].add(month)
        c["cum_oil"] += to_float(row.get("OIL"))
        c["cum_gas"] += to_float(row.get("GAS"))
        c["cum_water"] += to_float(row.get("WATER"))
    result = {"table_rows": rows, "properties": {}}
    for prop, c in sorted(cov.items()):
        months = sorted(c["months"])
        result["properties"][prop] = {
            "months": len(months),
            "first": months[0] if months else None,
            "last": months[-1] if months else None,
            "cum_oil": round(c["cum_oil"]),
            "cum_gas": round(c["cum_gas"]),
            "cum_water": round(c["cum_water"]),
        }
    out_json.write_text(json.dumps(result, indent=1))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("database")
    ap.add_argument("--out", default="_aries")
    args = ap.parse_args()

    db = Path(args.database)
    if not db.is_file():
        sys.exit(f"not a file: {db}")
    out = Path(args.out)
    (out / "tables").mkdir(parents=True, exist_ok=True)

    backend = resolve_backend(db)
    warnings: list[str] = []
    try:
        all_tables = backend.list_tables()
    except Exception as e:  # a corrupt/locked file should fail honestly
        sys.exit(f"backend {backend.name} could not open the database: {e}")

    by_upper = {t.upper(): t for t in all_tables}
    core_set = {t.upper() for t in CORE_TABLES}
    count_only = {t.upper() for t in COUNT_ONLY_TABLES}

    tables_out = []
    for upper in sorted(by_upper):
        actual = by_upper[upper]
        entry = {"name": upper, "rows": None, "role": "other", "dumped": False}
        try:
            if upper in core_set:
                entry["role"] = "core"
                n, truncated = dump_table(backend, actual, out / "tables" / f"{upper}.csv")
                entry["rows"], entry["dumped"] = n, n > 0
                if truncated:
                    entry["truncated_at"] = DUMP_ROW_CAP
                    warnings.append(f"{upper}: dump truncated at {DUMP_ROW_CAP:,} rows")
            elif upper == COVERAGE_TABLE:
                entry["role"] = "aggregate"
                cov = production_coverage(backend, out / "production_coverage.json")
                entry["rows"] = cov["table_rows"]
                entry["note"] = (f"streamed into production_coverage.json "
                                 f"({len(cov['properties'])} properties)")
            elif upper in count_only:
                entry["role"] = "aggregate"
                entry["rows"] = count_rows(backend, actual)
                entry["note"] = "count only — computed output, not dumped"
            else:
                entry["rows"] = count_rows(backend, actual)
        except Exception as e:
            entry["error"] = str(e)
            warnings.append(f"{upper}: {backend.name} failed to read it ({e})")
        tables_out.append(entry)

    schema_version = None
    ver_csv = out / "tables" / "ARIESSCHEMAVERSION.csv"
    if ver_csv.is_file():
        with open(ver_csv, newline="", encoding="utf-8") as f:
            first = next(csv.DictReader(f), None)
        if first:
            schema_version = " ".join(str(v) for v in first.values() if v)

    manifest = {
        "database": {"file": db.name, "size_bytes": db.stat().st_size,
                     "sha256": sha256_file(db)},
        "backend": backend.name,
        "schema_version": schema_version,
        "tables": tables_out,
        "warnings": warnings,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))

    # ── readable summary ─────────────────────────────────────────────────────
    lines = [f"# ARIES triage — {db.name}", "",
             f"- size: {db.stat().st_size:,} bytes · backend: {backend.name}"
             + (f" · schema version: {schema_version}" if schema_version else ""),
             f"- tables: {len(tables_out)}", "", "## Core tables (dumped to tables/)"]
    for t in tables_out:
        if t["role"] == "core" and t.get("rows"):
            lines.append(f"- {t['name']}: {t['rows']:,} rows"
                         + (" (TRUNCATED)" if t.get("truncated_at") else ""))
    absent = [c for c in sorted(core_set) if c not in by_upper]
    if absent:
        lines += ["", "Core tables not in this database: " + ", ".join(absent)]
    lines += ["", "## Aggregate-only tables (too big to dump)"]
    for t in tables_out:
        if t["role"] == "aggregate":
            lines.append(f"- {t['name']}: {t['rows']:,} rows — {t.get('note', '')}")
    lines += ["", "## Everything else"]
    for t in tables_out:
        if t["role"] == "other":
            n = f"{t['rows']:,}" if t.get("rows") is not None else "?"
            lines.append(f"- {t['name']}: {n} rows")
    if warnings:
        lines += ["", "## Warnings"] + [f"- {w}" for w in warnings]
    (out / "triage.md").write_text("\n".join(lines) + "\n")

    print(f"triage complete -> {out}/triage.md ({len(tables_out)} tables, "
          f"backend {backend.name}"
          + (f", {len(warnings)} warnings" if warnings else "") + ")")


if __name__ == "__main__":
    main()
