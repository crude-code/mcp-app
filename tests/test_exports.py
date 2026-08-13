"""CSV export lane: assembly is pure and the route is a real Starlette app.

Two things matter here and both are tested end to end. First, the export
carries *gross* physical volumes and the committed decline parameters — the
things a chat payload can't hold — at full monthly resolution. Second, the
download behaves like a file for a browser rather than a one-shot handoff to
a sandbox: it does not consume its token, it sets a filename, and it refuses
a link whose grant has gone.
"""
import csv
import io

import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

import server.uploads as uploads
from server import exports
from server.upload_tokens import UploadTokenStore


def _rows(csv_text):
    return list(csv.DictReader(io.StringIO(csv_text)))


# Two months of axis, two wells; the second comes online a month late so the
# pre-online zero is visible in the export.
_ECONOMICS = {
    "schedule": {
        "origin": "2026-08-01",
        "months": ["2026-08-01", "2026-09-01"],
        "by_well": {
            "33-007-01662": {"oil_bbl": [1000.0, 950.0], "gas_mcf": [2000.0, 1900.0],
                             "net_oil": [200.0, 190.0], "net_gas": [400.0, 380.0]},
            "33-007-00001": {"oil_bbl": [0.0, 500.0], "gas_mcf": [0.0, 800.0],
                             "net_oil": [0.0, 100.0], "net_gas": [0.0, 160.0]},
        },
    }
}

_FORECAST = {
    "forecasts": {
        "33-007-01662": {
            "oil": {"curve": {"qi": 950.0, "di": 0.061, "b": 0.9,
                              "terminal_di_monthly": 0.005,
                              "switch_month_from_peak": 102.3, "stream": "oil"}},
            "gas": {"curve": {"qi": 1900.0, "di": 0.048, "b": 1.1,
                              "terminal_di_monthly": 0.005,
                              "switch_month_from_peak": 81.4, "stream": "gas"}},
            "anchor_month": "2026-07-01",
            "status": "PRODUCING",
            "assertion": {
                "entry_id": "abc123def456",
                "asserted": {"oil": {"qi": 1000.0, "di": 0.061, "b": 0.9},
                             "gas": {"qi": 2000.0, "di": 0.048, "b": 1.1}},
                "uptime_factor": 0.95,
                "rationale": "Trailing six months clean; b from Bakken priors.",
            },
        }
    }
}


class FakeRunStore:
    def __init__(self, stages=None):
        self.stages = stages or {}

    def read_stage(self, run_id, *, stage):
        return self.stages.get(stage)


@pytest.fixture
def rig():
    mcp = FastMCP("export-test")
    tokens = UploadTokenStore(ttl_seconds=60.0)
    runs = FakeRunStore({"economics": _ECONOMICS, "forecast": _FORECAST})
    uploads.register_upload_routes(mcp, tokens=tokens, extraction_store=None,
                                   run_store=runs)
    return TestClient(mcp.http_app()), tokens, runs


def _token(tokens, **meta):
    base = {"kind": "volumes", "run_id": "run-1", "sql": None, "schema": "public"}
    base.update(meta)
    return tokens.mint(user_id=7, user_slug="acme", purpose="export", meta=base)


# ── assembly ────────────────────────────────────────────────────────────────

def test_volumes_are_gross_and_monthly_per_well():
    text, n = exports.build_volumes_csv(_ECONOMICS)
    rows = _rows(text)
    assert n == 4                                  # 2 wells x 2 months, rectangular
    first = rows[0]
    assert first["well_api"] == "33-007-00001"     # sorted by api
    assert first["month"] == "2026-08-01"
    assert first["month_index"] == "0"
    # Gross is untouched by interest; net is the scaled twin, both present.
    subject = [r for r in rows if r["well_api"] == "33-007-01662"][0]
    assert subject["oil_bbl"] == "1000.0"
    assert subject["gas_mcf"] == "2000.0"
    assert subject["net_oil"] == "200.0"
    # No revenue/cashflow leakage — a volumes export is not an econ export.
    assert set(subject) == {"well_api", "month", "month_index",
                            "oil_bbl", "gas_mcf", "net_oil", "net_gas"}


def test_volumes_keep_pre_online_zeros():
    """A well that comes online late still gets a row for every month, so a
    downstream load never has to infer a gap."""
    rows = _rows(exports.build_volumes_csv(_ECONOMICS)[0])
    late = [r for r in rows if r["well_api"] == "33-007-00001"]
    assert [r["oil_bbl"] for r in late] == ["0.0", "500.0"]


def test_volumes_without_by_well_explains_itself():
    with pytest.raises(exports.ExportError, match="exceeds"):
        exports.build_volumes_csv(
            {"schedule": {"months": [], "by_well_omitted": "900 wells exceeds the 200-well audit cap"}}
        )
    with pytest.raises(exports.ExportError, match="run_valuation"):
        exports.build_volumes_csv({})


def test_parameters_carry_both_committed_and_asserted_qi():
    text, n = exports.build_parameters_csv(_FORECAST)
    rows = _rows(text)
    assert n == 2                                  # one row per stream
    oil = [r for r in rows if r["stream"] == "oil"][0]
    # Committed qi is uptime-scaled (1000 x 0.95); asserted is what Claude said.
    assert oil["qi_committed"] == "950.0"
    assert oil["qi_asserted"] == "1000.0"
    assert oil["uptime_factor"] == "0.95"
    assert oil["anchor_month"] == "2026-07-01"
    assert oil["b"] == "0.9"
    assert oil["switch_month_from_anchor"] == "102.3"
    assert "Bakken priors" in oil["rationale"]
    # Oil and gas are independent rows — never one shared shape.
    gas = [r for r in rows if r["stream"] == "gas"][0]
    assert gas["b"] == "1.1"
    assert gas["qi_committed"] == "1900.0"


def test_parameters_replay_legacy_qi_peak():
    legacy = {"forecasts": {"33-1": {"oil": {"curve": {"qi_peak": 800.0, "di": 0.07, "b": 1.0,
                                                       "terminal_di_monthly": 0.005,
                                                       "switch_month_from_peak": None}}}}}
    rows = _rows(exports.build_parameters_csv(legacy)[0])
    assert rows[0]["qi_committed"] == "800.0"


def test_parameters_without_forecast_stage():
    with pytest.raises(exports.ExportError, match="forecast_wells"):
        exports.build_parameters_csv({})


def test_filename_is_recognisable_and_safe():
    name = exports.filename_for("volumes", run_id="913983bd-a388", label="Covenant / Q3 Deal")
    assert name.startswith("crudecode-volumes-covenant---q3-deal-")
    assert name.endswith(".csv")
    assert "/" not in name


def test_assemble_rejects_unknown_kind():
    with pytest.raises(exports.ExportError, match="unknown export kind"):
        exports.assemble("everything", {})


def test_volume_columns_track_the_schedule():
    """Drift guard: the export reads columns the orchestrator writes. Renaming
    one there without here would ship a CSV of silent zeros."""
    from server.valuation.orchestrator import _SCHEDULE_COLS
    assert set(exports._VOLUME_COLS) <= set(_SCHEDULE_COLS)


# ── the route ───────────────────────────────────────────────────────────────

def test_download_serves_a_csv_attachment(rig):
    client, tokens, _ = rig
    r = client.get(f"/export/{_token(tokens)}/crudecode-volumes.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="crudecode-volumes.csv"'
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-export-rows"] == "4"
    assert r.text.splitlines()[0] == "well_api,month,month_index,oil_bbl,gas_mcf,net_oil,net_gas"


def test_download_is_repeatable(rig):
    """A browser retries, a person double-clicks, a download manager issues a
    range request. Unlike the upload routes, this token survives being used."""
    client, tokens, _ = rig
    token = _token(tokens)
    for _ in range(3):
        assert client.get(f"/export/{token}/x.csv").status_code == 200


def test_expired_or_unknown_link_is_410(rig):
    client, _, _ = rig
    r = client.get("/export/not-a-real-token/x.csv")
    assert r.status_code == 410
    assert "export again" in r.json()["error"]


def test_upload_token_cannot_be_redeemed_as_an_export(rig):
    client, tokens, _ = rig
    kit = tokens.mint(user_id=7, user_slug="acme", purpose="kit", meta={})
    assert client.get(f"/export/{kit}/x.csv").status_code == 410


def test_parameters_kind_routes_to_the_forecast_stage(rig):
    client, tokens, _ = rig
    r = client.get(f"/export/{_token(tokens, kind='parameters')}/p.csv")
    assert r.status_code == 200
    assert r.text.splitlines()[0].startswith("well_api,stream,qi_committed,qi_asserted")


def test_missing_stage_is_422_not_500(rig):
    client, tokens, _ = rig
    empty = FakeRunStore({})
    mcp = FastMCP("export-empty")
    uploads.register_upload_routes(mcp, tokens=tokens, extraction_store=None,
                                   run_store=empty)
    c = TestClient(mcp.http_app())
    r = c.get(f"/export/{_token(tokens)}/x.csv")
    assert r.status_code == 422
    assert "nothing to export" in r.json()["error"]


def test_filename_from_the_url_cannot_inject_a_header(rig):
    client, tokens, _ = rig
    r = client.get(f'/export/{_token(tokens)}/eb"il;drop.csv')
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="ebildrop.csv"'


def test_export_ttl_outlives_the_upload_default():
    """Uploads are redeemed by a sandbox immediately; an export link waits on
    a human, so its grant carries its own longer lifetime."""
    tokens = UploadTokenStore(ttl_seconds=60.0)
    token = tokens.mint(user_id=1, user_slug="acme", purpose="export",
                        meta={"kind": "volumes"}, ttl_seconds=24 * 3600)
    grant = tokens.claim(token, purpose="export")
    assert grant is not None and grant.ttl_seconds == 24 * 3600
