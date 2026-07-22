#!/usr/bin/env python3
"""Deterministic dataroom triage walker (bundled with the dataroom-extract skill).

Run this FIRST, right after unzipping a dataroom, so you have a clean inventory
before you start reading. It walks every file, hashes it, classifies by type, and
dumps the machine-readable content of spreadsheets and text-PDFs into `_triage/`
so you read structured content instead of opening binaries by hand.

    python3 triage.py <dataroom_dir>

Writes, under <dataroom_dir>/_triage/:
    manifest.json        one entry per file (path, size, type, sha256, artifacts)
    triage.md            human-readable inventory
    xlsx/<name>.json     each workbook: sheet names, columns, sample rows
    pdf/<name>.txt       each text-PDF: page-marked extracted text

Dependencies: openpyxl, pdfplumber (both preinstalled in the code-execution
sandbox). Pure stdlib otherwise. Safe to re-run.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

TRIAGE_DIR = "_triage"
EXT_TYPES = {
    ".xlsx": "xlsx", ".xlsm": "xlsx", ".xls": "xls",
    ".pdf": "pdf", ".zip": "zip", ".csv": "csv", ".tsv": "tsv",
    ".json": "json", ".txt": "txt", ".md": "txt",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".tif": "image", ".tiff": "image", ".docx": "docx", ".doc": "doc",
}
SAMPLE_FIRST, SAMPLE_LAST, TRUNCATE_AT = 50, 10, 500


def classify(p: Path) -> str:
    return EXT_TYPES.get(p.suffix.lower(), "other")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        parts = p.relative_to(root).parts
        if parts and parts[0] == TRIAGE_DIR:           # skip our own output
            continue
        if p.name == ".DS_Store" or p.name.startswith("._"):  # macOS noise
            continue
        yield p


def dump_xlsx(src: Path, out: Path) -> bool:
    try:
        import openpyxl
    except ImportError:
        return False
    try:
        wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    except Exception:
        return False
    sheets = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            sheets.append({"name": ws.title, "n_rows": 0, "columns": [],
                           "sample_rows": [], "truncated": False})
            continue
        headers = [str(c) if c is not None else "" for c in rows[0]]
        data = rows[1:]
        trunc = len(data) > TRUNCATE_AT
        sample = (data[:SAMPLE_FIRST] + data[-SAMPLE_LAST:]) if trunc else data
        sheets.append({
            "name": ws.title, "n_rows": len(data), "columns": headers,
            "sample_rows": [dict(zip(headers, r)) for r in sample], "truncated": trunc,
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"path": src.name, "sheets": sheets}, indent=2, default=str))
    return True


def dump_pdf(src: Path, out: Path):
    try:
        import pdfplumber
    except ImportError:
        return (False, None)
    try:
        with pdfplumber.open(src) as pdf:
            pages, any_text = [], False
            for i, page in enumerate(pdf.pages, start=1):
                t = page.extract_text() or ""
                if t.strip():
                    any_text = True
                pages.append((i, t))
    except Exception:
        return (False, None)
    n = len(pages)
    if not any_text:
        return (False, n)                              # image-only scan
    out.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for i, t in pages:
        body.extend([f"=== PAGE {i} ===", t.rstrip(), ""])
    out.write_text("\n".join(body))
    return (True, n)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python3 triage.py <dataroom_dir>")
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")
    triage = root / TRIAGE_DIR

    entries = []
    for src in walk(root):
        rel = src.relative_to(root).as_posix()
        ftype = classify(src)
        e = {"path": rel, "size_bytes": src.stat().st_size, "file_type": ftype,
             "sha256": sha256_file(src), "artifacts": [], "notes": None}
        if ftype == "xlsx":
            out = triage / "xlsx" / (src.stem + ".json")
            if dump_xlsx(src, out):
                e["artifacts"].append(out.relative_to(root).as_posix())
            else:
                e["notes"] = "could not read workbook"
        elif ftype == "pdf":
            out = triage / "pdf" / (src.stem + ".txt")
            ok, n = dump_pdf(src, out)
            e["page_count"] = n
            e["pdf_extractable"] = ok
            if ok:
                e["artifacts"].append(out.relative_to(root).as_posix())
            else:
                e["notes"] = "image-only or unreadable PDF — no text extracted (OCR not run)"
        elif ftype in ("xls", "doc"):
            e["notes"] = f"legacy {ftype} format — convert if you need its contents"
        elif ftype == "zip" and ("ARIES" in src.name.upper() or "ACCDB" in src.name.upper()):
            e["notes"] = "Aries .accdb suspected — not parsed"
        entries.append(e)

    triage.mkdir(parents=True, exist_ok=True)
    (triage / "manifest.json").write_text(json.dumps(
        {"dataroom_root": root.name, "n_files": len(entries), "files": entries}, indent=2))

    by_type: dict[str, int] = {}
    for e in entries:
        by_type[e["file_type"]] = by_type.get(e["file_type"], 0) + 1
    lines = [f"# Triage: {root.name}", "", f"{len(entries)} files", "", "## By type"]
    lines += [f"- {t}: {c}" for t, c in sorted(by_type.items(), key=lambda kv: -kv[1])]
    lines += ["", "## Files"]
    for e in entries:
        flags = []
        if e["artifacts"]:
            flags.append("→ " + ", ".join(e["artifacts"]))
        if e["notes"]:
            flags.append(f"({e['notes']})")
        lines.append(f"- `{e['path']}` [{e['file_type']}, {e['size_bytes']:,}B] {' '.join(flags)}")
    (triage / "triage.md").write_text("\n".join(lines))

    print(f"triaged {len(entries)} files -> {triage}/manifest.json")
    print("by type:", ", ".join(f"{t}={c}" for t, c in sorted(by_type.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
