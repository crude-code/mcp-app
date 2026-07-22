"""End-to-end guarantee for the persist kit: what persist_pack.py prints,
extraction_transport.py must expand back to the original rows. Runs the
packer as a subprocess (the way the sandbox does) against the skill's
bundled example.json."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from server import extraction_transport as transport

_SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "dataroom-extract"
_PACK = _SKILL_DIR / "persist_pack.py"
_EXAMPLE = _SKILL_DIR / "example.json"


def _run_pack(*flags):
    proc = subprocess.run(
        [sys.executable, str(_PACK), str(_EXAMPLE), *flags],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def example():
    return json.loads(_EXAMPLE.read_text())


def test_headers_match_transport_contract():
    spec = importlib.util.spec_from_file_location("persist_pack", _PACK)
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    assert pack.PRODUCTION_HEADER == transport.PRODUCTION_HEADER
    assert pack.REVENUE_HEADER == transport.REVENUE_HEADER
    assert pack.ENTITY_LISTS == transport.ENTITY_LISTS


def test_default_kit_omits_production_and_notes_it(example):
    kit = _run_pack()
    assert kit["production_csv"] is None
    assert kit["extraction"]["production_history"] == []
    assert kit["extraction"]["revenue_observations"] == []
    assert "[persist] production_history (1 rows) not persisted" in kit["extraction"]["extraction_notes"]
    # original notes are preserved, the persist note is appended
    assert example["extraction_notes"] in kit["extraction"]["extraction_notes"]
    assert kit["counts"]["production_history"] == 1
    assert kit["expected_stored"]["production_history"] == 0
    assert kit["expected_stored"]["revenue_observations"] == 2


def test_kit_round_trips_through_transport(example):
    kit = _run_pack("--with-production")
    full = transport.unpack_extraction(
        kit["extraction"],
        production_csv=kit["production_csv"],
        revenue_csv=kit["revenue_csv"],
        sources=kit["sources"],
    )
    assert transport.entity_counts(full) == kit["expected_stored"]

    # Every unpacked row must equal the original — values and provenance.
    for key, header in (
        ("revenue_observations", transport.REVENUE_HEADER),
        ("production_history", transport.PRODUCTION_HEADER),
    ):
        for got, orig in zip(full[key], example[key], strict=True):
            for col in header:
                if col in ("src", "row", "notes"):
                    continue
                assert got[col] == orig.get(col), f"{key}.{col}"
            assert got["provenance"] == orig["provenance"], f"{key}.provenance"

    # Non-packed entities ride through untouched.
    for key in ("deal", "wells", "interests", "expenses", "documents"):
        assert full[key] == example[key]


def test_with_production_keeps_notes_clean(example):
    kit = _run_pack("--with-production")
    assert "[persist]" not in (kit["extraction"]["extraction_notes"] or "")
    assert kit["expected_stored"] == kit["counts"]
