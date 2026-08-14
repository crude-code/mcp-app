"""The dataroom viewer's data contract: viewer_payload.py's derived rollups
(LTM windows, revenue shares, interest sums, status groups, document folders)
and the drift pin between the payload the script emits and the fields the
frozen DataroomViewer.jsx template consumes — two files that never import
each other, same trick as test_template_publish_drift.py."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "dataroom-extract"
_SCRIPT = _SKILL_DIR / "viewer_payload.py"
_TEMPLATE = _SKILL_DIR / "DataroomViewer.jsx"
_EXAMPLE = _SKILL_DIR / "example.json"

spec = importlib.util.spec_from_file_location("viewer_payload", _SCRIPT)
vp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vp)


def _prov(notes=None):
    return {"source_file": "room/a.xlsx", "source_locator": "sheet:S;row:2", "notes": notes}


def _well(api, name, well_type="PDP", **kw):
    return {"provenance": _prov(), "api": api, "name": name, "well_type": well_type, **kw}


def _rev(api, prod_date, net, identifier=None):
    return {"provenance": _prov(), "well_api": api, "well_identifier": identifier,
            "prod_date": prod_date, "net_revenue": net}


# ── LTM rollups ──────────────────────────────────────────────────────────────

def test_ltm_window_rollups_and_shares():
    ext = {
        "wells": [_well("42-1", "Alpha"), _well("42-2", "Beta")],
        "interests": [],
        "revenue_observations": [
            _rev("42-1", "2026-05-01", 100.0),
            _rev("42-1", "2025-06-01", 50.0),   # first month inside the window
            _rev("42-1", "2025-05-01", 999.0),  # 13 months back — excluded
            _rev("42-2", "2026-01-01", 350.0),
        ],
    }
    p = vp.build_payload(ext)
    assert p["ltm_window"] == {"start": "2025-06", "end": "2026-05"}
    rows = {r["name"]: r for r in p["manifest"][0]["wells"]}
    assert rows["Alpha"]["ltm_net_revenue"] == 150.0
    assert rows["Beta"]["ltm_net_revenue"] == 350.0
    assert rows["Beta"]["revenue_share_pct"] == 70.0
    assert p["stats"]["ltm_net_revenue"] == 500.0
    assert p["stats"]["ltm_net_revenue_mo"] == round(500.0 / 12, 2)
    # sorted by LTM desc within the group
    assert [r["name"] for r in p["manifest"][0]["wells"]] == ["Beta", "Alpha"]


def test_ltm_window_ending_in_december():
    ext = {
        "wells": [_well("42-1", "Alpha")],
        "interests": [],
        "revenue_observations": [
            _rev("42-1", "2025-12-01", 10.0),
            _rev("42-1", "2025-01-01", 1.0),    # January is inside a Dec-ending window
            _rev("42-1", "2024-12-01", 999.0),  # excluded
        ],
    }
    p = vp.build_payload(ext)
    assert p["ltm_window"] == {"start": "2025-01", "end": "2025-12"}
    assert p["manifest"][0]["wells"][0]["ltm_net_revenue"] == 11.0


def test_revenue_joins_by_identifier_when_api_missing():
    ext = {
        "wells": [_well(None, "Falcon 2H")],
        "interests": [],
        "revenue_observations": [_rev(None, "2026-01-01", 42.0, identifier="FALCON 2H")],
    }
    p = vp.build_payload(ext)
    assert p["manifest"][0]["wells"][0]["ltm_net_revenue"] == 42.0


# ── interests ────────────────────────────────────────────────────────────────

def test_interest_sums_percent_conversion_and_notes():
    note = "Payout-sensitive: BPO reverts APO."
    ext = {
        "wells": [_well("42-1", "Alpha")],
        "interests": [
            {"provenance": _prov(note), "well_api": "42-1", "wi_decimal": 0.20, "nri_decimal": 0.15},
            {"provenance": _prov(), "well_api": "42-1", "wi_decimal": 0.08125, "nri_decimal": 0.06},
        ],
        "revenue_observations": [],
    }
    row = vp.build_payload(ext)["manifest"][0]["wells"][0]
    assert row["wi_pct"] == 28.125
    assert row["nri_pct"] == 21.0
    assert row["note"] == note


def test_stats_wi_spread():
    ext = {
        "wells": [_well("42-1", "A"), _well("42-2", "B")],
        "interests": [
            {"provenance": _prov(), "well_api": "42-1", "wi_decimal": 0.01},
            {"provenance": _prov(), "well_api": "42-2", "wi_decimal": 0.03},
        ],
        "revenue_observations": [],
    }
    s = vp.build_payload(ext)["stats"]
    assert (s["avg_wi_pct"], s["wi_min_pct"], s["wi_max_pct"]) == (2.0, 1.0, 3.0)


# ── grouping / spines ────────────────────────────────────────────────────────

def test_status_groups_ordered_pdp_first():
    ext = {
        "wells": [_well("42-3", "Undrilled 1", well_type="PUD"),
                  _well("42-1", "Producer", well_type="PDP"),
                  _well("42-2", "Ducked", well_type="DUC")],
        "interests": [], "revenue_observations": [],
    }
    groups = vp.build_payload(ext)["manifest"]
    assert [g["status"] for g in groups] == ["PDP", "DUC", "PUD"]
    assert groups[2]["label"] == "Undrilled"


def test_tracts_spine():
    ext = {
        "wells": [],
        "tracts": [{"provenance": _prov(), "name": "Tract 1", "county": "Reeves",
                    "state": "TX", "gross_acres": 640.0, "nma": 80.0, "nra": 20.0,
                    "royalty_decimal": 0.25, "lessee": "Cimarex"}],
        "interests": [], "revenue_observations": [],
    }
    p = vp.build_payload(ext)
    assert p["manifest"] == []
    assert p["tracts"][0]["royalty_pct"] == 25.0
    assert p["stats"]["tract_count"] == 1


def test_documents_grouped_by_last_two_segments():
    docs = [
        {"provenance": _prov(), "path": "Room158/Check Stubs/a.pdf", "category": "financial"},
        {"provenance": _prov(), "path": "Room158/Check Stubs/b.pdf", "category": "financial"},
        {"provenance": _prov(), "path": "Room158/Title/do.pdf", "category": "title"},
        {"provenance": _prov(), "path": "teaser.pdf", "category": "marketing"},
    ]
    groups = vp.build_payload({"documents": docs})["documents"]
    assert [(g["folder"], g["count"]) for g in groups] == [
        ("Room158/Check Stubs", 2), ("(root)", 1), ("Room158/Title", 1)]
    assert groups[0]["files"] == ["a.pdf", "b.pdf"]
    assert groups[2]["categories"] == "title"


def test_documents_nested_folders_keep_operator_context():
    """operator/year/month trees must not collapse into folders named
    after bare years — the failure the Tonka room surfaced."""
    docs = [
        {"provenance": _prov(), "path": "Check Stubs/Kraken/2025/1-2025.pdf",
         "category": "financial"},
        {"provenance": _prov(), "path": "Check Stubs/Murex/2025/1-2025.pdf",
         "category": "financial"},
    ]
    groups = vp.build_payload({"documents": docs})["documents"]
    assert sorted(g["folder"] for g in groups) == ["Kraken/2025", "Murex/2025"]


def test_flags_passthrough_and_default():
    assert vp.build_payload({})["flags"] == []
    assert vp.build_payload({"flags": ["Reversion not modeled."]})["flags"] == ["Reversion not modeled."]


# ── the worked example, through the CLI the sandbox runs ─────────────────────

def test_example_payload_cli():
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(_EXAMPLE)],
        capture_output=True, text=True, check=True,
    )
    p = json.loads(proc.stdout)
    assert p["stats"]["well_count"] == 2
    assert p["manifest"][0]["status"] == "PDP"
    assert len(p["flags"]) == 2                       # example.json models the flags list
    assert p["notes"]                                 # extraction_notes passthrough
    assert p["ltm_window"] is not None
    # every derived dollar figure is a clean float, never NaN/strings
    for row in p["manifest"][0]["wells"]:
        assert row["ltm_net_revenue"] is None or isinstance(row["ltm_net_revenue"], (int, float))


# ── payload ⇄ template drift pin ─────────────────────────────────────────────
# The script and the frozen JSX never import each other; this list is the one
# place the contract is written down twice-checked: the payload must emit
# exactly these keys, and the template must reference every accessor it
# renders. Rename a field in either file and this fails.

PAYLOAD_TOP_KEYS = {"deal", "stats", "flags", "notes", "ltm_window",
                    "manifest", "tracts", "documents"}
STATS_KEYS = {"well_count", "tract_count", "doc_count", "net_boed",
              "seller_pv10_mm", "ltm_net_revenue", "ltm_net_revenue_mo",
              "avg_wi_pct", "wi_min_pct", "wi_max_pct"}
ROW_KEYS = {"api", "name", "operator", "formation", "basin", "county", "state",
            "wi_pct", "nri_pct", "ri_pct", "lateral_ft", "first_prod",
            "ltm_net_revenue", "revenue_share_pct", "note"}
GROUP_KEYS = {"status", "label", "well_count", "ltm_net_revenue", "wells"}
DOC_KEYS = {"folder", "count", "categories", "files"}
TEMPLATE_ACCESSORS = [
    "data.deal", "data.stats", "data.manifest", "data.tracts",
    "data.documents", "data.flags", "data.notes", "data.ltm_window",
    "deal.seller", "deal.broker", "deal.basin", "deal.state", "deal.category",
    "deal.asset_type", "deal.process_type", "deal.bid_due_date", "deal.effective_date",
    "stats.well_count", "stats.tract_count", "stats.net_boed", "stats.seller_pv10_mm",
    "stats.ltm_net_revenue_mo", "stats.avg_wi_pct", "stats.wi_min_pct",
    "stats.wi_max_pct", "stats.doc_count",
    "group.status", "group.label", "group.well_count", "group.ltm_net_revenue",
    "group.wells", "group.folder", "group.count", "group.categories", "group.files",
    "r.wi_pct", "r.nri_pct", "r.ri_pct", "r.lateral_ft", "r.first_prod",
    "r.ltm_net_revenue", "r.revenue_share_pct", "r.note",
    "t.royalty_pct", "t.gross_acres", "t.nma", "t.nra", "t.legal_description",
]
FILL_MARKERS = ['const DATA = null;', 'const TITLE = "";', 'const TLDR = "";']


def test_payload_emits_exactly_the_pinned_contract():
    with open(_EXAMPLE) as f:
        p = vp.build_payload(json.load(f))
    assert set(p) == PAYLOAD_TOP_KEYS
    assert set(p["stats"]) == STATS_KEYS
    assert set(p["manifest"][0]) == GROUP_KEYS
    assert {k for r in p["manifest"][0]["wells"] for k in r} == ROW_KEYS
    assert all(set(d) == DOC_KEYS for d in p["documents"])
    assert set(p["ltm_window"]) == {"start", "end"}


def test_template_references_the_pinned_contract():
    src = _TEMPLATE.read_text()
    missing = [a for a in TEMPLATE_ACCESSORS if a not in src]
    assert not missing, f"DataroomViewer.jsx no longer references: {missing}"
    for marker in FILL_MARKERS:
        assert src.count(marker) == 1, f"fill marker {marker!r} must appear exactly once"
    assert "recharts" not in src and "lucide" not in src, "viewer must stay react-only"
