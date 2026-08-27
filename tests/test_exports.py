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
import zipfile

import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

import server.uploads as uploads
from server import export_tokens, exports
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
                             "net_oil": [200.0, 190.0], "net_gas": [400.0, 380.0],
                             "gross_rev": [95000.0, 90000.0],
                             "net_rev": [19000.0, 18000.0],
                             "sev_tax": [1425.0, 1350.0], "gpt": [800.0, 760.0],
                             "capex": [0.0, 0.0], "opex": [3000.0, 3000.0],
                             "net_cashflow": [13775.0, 12890.0]},
            "33-007-00001": {"oil_bbl": [0.0, 500.0], "gas_mcf": [0.0, 800.0],
                             "net_oil": [0.0, 100.0], "net_gas": [0.0, 160.0],
                             "gross_rev": [0.0, 48000.0],
                             "net_rev": [0.0, 9600.0],
                             "sev_tax": [0.0, 720.0], "gpt": [0.0, 400.0],
                             "capex": [0.0, 0.0], "opex": [0.0, 2500.0],
                             "net_cashflow": [0.0, 5980.0]},
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
    with pytest.raises(exports.ExportError, match="no economics stage"):
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
    with pytest.raises(exports.ExportError, match="deal_forecast_wells"):
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


# ── the bundle ──────────────────────────────────────────────────────────────

def test_cashflow_carries_every_line_item():
    """Where `volumes` is deliberately narrow, the bundle's table is the whole
    schedule — and the cashflow identity has to survive the trip to CSV."""
    text, n = exports.build_cashflow_csv(_ECONOMICS)
    rows = _rows(text)
    assert n == 4
    subject = [r for r in rows if r["well_api"] == "33-007-01662"][0]
    assert set(subject) == {"well_api", "month", "month_index", *exports._CASHFLOW_COLS}
    got = (float(subject["net_rev"]) - float(subject["sev_tax"])
           - float(subject["gpt"]) - float(subject["capex"]) - float(subject["opex"]))
    assert got == pytest.approx(float(subject["net_cashflow"]))


def test_cashflow_columns_track_the_schedule():
    """Tighter than the volumes guard: the bundle claims to carry *everything*
    the orchestrator computes, so a new column there must appear here too."""
    from server.valuation.orchestrator import _SCHEDULE_COLS
    assert exports._CASHFLOW_COLS == _SCHEDULE_COLS


def _members(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return {n: z.read(n).decode() for n in z.namelist()}


def test_bundle_packs_the_tables_and_a_readme():
    blob, rows = exports.build_bundle_zip(_ECONOMICS, _FORECAST, run_id="run-1")
    files = _members(blob)
    assert set(files) == {"wells_monthly.csv", "parameters.csv", "README.txt"}
    assert rows == 6                               # 4 well-months + 2 curve rows
    assert files["wells_monthly.csv"].splitlines()[0].endswith("net_cashflow")
    readme = files["README.txt"]
    assert "run-1" in readme
    assert "parameters.csv" in readme              # documented because present
    assert "net_cashflow = net_rev - sev_tax - gpt - capex - opex" in readme


def test_bundle_without_a_forecast_stage_still_builds():
    """Parameters ride along when they can be read; losing them costs the file,
    not the bundle — and the README stops advertising what isn't inside."""
    blob, rows = exports.build_bundle_zip(_ECONOMICS, None, run_id="run-1")
    files = _members(blob)
    assert set(files) == {"wells_monthly.csv", "README.txt"}
    assert rows == 4
    assert "parameters.csv" not in files["README.txt"]


def test_bundle_needs_the_economics_stage():
    with pytest.raises(exports.ExportError, match="no economics stage"):
        exports.build_bundle_zip({}, _FORECAST, run_id="run-1")


def test_bundle_filename_is_a_zip():
    assert exports.filename_for("bundle", run_id="abc123def").endswith(".zip")
    assert exports.filename_for("volumes", run_id="abc123def").endswith(".csv")
    assert exports.media_type_for("bundle") == "application/zip"


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
    assert "expired" in r.text


def test_failures_render_as_a_page_not_json(rig):
    """This route's client is a browser — often opened from a deal sheet weeks
    after the session. A JSON blob reads as broken; a sentence reads as
    expired, which is usually what happened."""
    client, _, _ = rig
    r = client.get("/export/not-a-real-token/x.csv")
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    assert "<title>" in r.text and "export the run again" in r.text
    assert "{message}" not in r.text                  # template actually filled


def test_upload_token_cannot_be_redeemed_as_an_export(rig):
    client, tokens, _ = rig
    kit = tokens.mint(user_id=7, user_slug="acme", purpose="kit", meta={})
    assert client.get(f"/export/{kit}/x.csv").status_code == 410


def test_parameters_kind_routes_to_the_forecast_stage(rig):
    client, tokens, _ = rig
    r = client.get(f"/export/{_token(tokens, kind='parameters')}/p.csv")
    assert r.status_code == 200
    assert r.text.splitlines()[0].startswith("well_api,stream,qi_committed,qi_asserted")


def test_download_serves_a_zip_that_actually_unzips(rig):
    """The one thing the CSV kinds never proved: bytes survive the route."""
    client, tokens, _ = rig
    r = client.get(f"/export/{_token(tokens, kind='bundle')}/crudecode-bundle.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="crudecode-bundle.zip"'
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert z.testzip() is None
        assert "wells_monthly.csv" in z.namelist()


def test_missing_stage_is_422_not_500(rig):
    client, tokens, _ = rig
    empty = FakeRunStore({})
    mcp = FastMCP("export-empty")
    uploads.register_upload_routes(mcp, tokens=tokens, extraction_store=None,
                                   run_store=empty)
    c = TestClient(mcp.http_app())
    r = c.get(f"/export/{_token(tokens)}/x.csv")
    assert r.status_code == 422
    assert "nothing to export" in r.text


def test_filename_from_the_url_cannot_inject_a_header(rig):
    client, tokens, _ = rig
    r = client.get(f'/export/{_token(tokens)}/eb"il;drop.csv')
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="ebildrop.csv"'


# ── signed grants ───────────────────────────────────────────────────────────

_KEY = b"test-signing-key"


def test_signed_token_round_trips_its_facts():
    tok = export_tokens.mint(kind="bundle", run_id="run-1", user_id=7,
                             user_slug="acme", key=_KEY)
    claims = export_tokens.verify(tok, key=_KEY)
    assert claims["kind"] == "bundle"
    assert claims["run_id"] == "run-1"
    assert claims["user_id"] == 7 and claims["user_slug"] == "acme"


def test_signed_token_needs_no_server_memory():
    """The whole point: a fresh process with only the secret can still honour a
    link minted before it started. Nothing is looked up."""
    tok = export_tokens.mint(kind="volumes", run_id="run-1", user_id=7,
                             user_slug="acme", key=_KEY)
    assert export_tokens.verify(tok, key=b"test-signing-key")["run_id"] == "run-1"


@pytest.mark.parametrize("mangle", [
    lambda t: t[:-2] + ("aa" if not t.endswith("aa") else "bb"),   # bad signature
    lambda t: t.replace(".", "", 1),                                # no separator
    lambda t: "@@@." + t.split(".", 1)[1],                          # unbase64able head
])
def test_tampered_tokens_are_refused(mangle):
    tok = export_tokens.mint(kind="bundle", run_id="run-1", user_id=7,
                             user_slug="acme", key=_KEY)
    with pytest.raises(export_tokens.ExportTokenError):
        export_tokens.verify(mangle(tok), key=_KEY)


def test_a_forged_payload_does_not_verify():
    """Swapping the run id for someone else's without the key must fail."""
    import base64 as _b64, json as _json
    head, _, sig = export_tokens.mint(kind="bundle", run_id="run-1", user_id=7,
                                      user_slug="acme", key=_KEY).partition(".")
    claims = _json.loads(export_tokens._unb64(head))
    claims["r"] = "someone-elses-run"
    forged = _b64.urlsafe_b64encode(
        _json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    with pytest.raises(export_tokens.ExportTokenError, match="signature"):
        export_tokens.verify(f"{forged}.{sig}", key=_KEY)


def test_expired_signed_token_says_so():
    tok = export_tokens.mint(kind="bundle", run_id="run-1", user_id=7,
                             user_slug="acme", ttl_seconds=-1, key=_KEY)
    with pytest.raises(export_tokens.ExportTokenError, match="expired"):
        export_tokens.verify(tok, key=_KEY)


def test_query_is_not_signable():
    """A SELECT is too large for a URL and not a thing to publish in one, so
    `query` keeps the in-memory ticket rather than getting a weaker signature."""
    assert "query" not in export_tokens.SIGNABLE_KINDS
    with pytest.raises(export_tokens.ExportTokenError, match="not signable"):
        export_tokens.mint(kind="query", run_id="", user_id=7,
                           user_slug="acme", key=_KEY)


def test_no_secret_means_no_signing(monkeypatch):
    monkeypatch.delenv("CC_EXPORT_SECRET", raising=False)
    assert export_tokens.secret() is None
    monkeypatch.setenv("CC_EXPORT_SECRET", "  ")
    assert export_tokens.secret() is None
    monkeypatch.setenv("CC_EXPORT_SECRET", "hunter2")
    assert export_tokens.secret() == b"hunter2"


def test_signed_link_is_honoured_by_the_route(rig, monkeypatch):
    """End to end: a token the store has never heard of still downloads."""
    client, tokens, _ = rig
    monkeypatch.setenv("CC_EXPORT_SECRET", "test-signing-key")
    tok = export_tokens.mint(kind="bundle", run_id="run-1", user_id=7,
                             user_slug="acme")
    assert tokens.claim(tok, purpose="export") is None      # not in memory
    r = client.get(f"/export/{tok}/crudecode-bundle.zip")
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert "wells_monthly.csv" in z.namelist()


# ── the deal sheet's download row ───────────────────────────────────────────

def test_run_scoped_mint_is_durable_when_a_secret_exists(monkeypatch):
    import server.mcp_server as srv
    monkeypatch.setenv("CC_EXPORT_SECRET", "test-signing-key")
    url, filename, durable = srv._mint_export_url(
        {"user_id": 9999, "user_slug": "test-user"},
        kind="bundle", run_id="run-1", label="Tonka Package")
    assert durable is True
    assert filename.endswith(".zip") and "tonka-package" in filename
    token = url.split("/export/")[1].split("/")[0]
    assert export_tokens.verify(token)["run_id"] == "run-1"


def test_query_and_secretless_mints_fall_back_to_the_ticket(monkeypatch):
    import server.mcp_server as srv
    monkeypatch.setenv("CC_EXPORT_SECRET", "test-signing-key")
    _url, _fn, durable = srv._mint_export_url(
        {"user_id": 9999, "user_slug": "test-user"},
        kind="query", sql="SELECT 1")
    assert durable is False                     # signable kinds only

    monkeypatch.delenv("CC_EXPORT_SECRET", raising=False)
    url, _fn, durable = srv._mint_export_url(
        {"user_id": 9999, "user_slug": "test-user"}, kind="bundle", run_id="run-1")
    assert durable is False                     # no secret, no durable link
    token = url.split("/export/")[1].split("/")[0]
    assert srv._upload_tokens.claim(token, purpose="export") is not None


def test_deal_sheet_reads_the_field_the_server_writes():
    """The download row is the one place the frozen template reaches for a key
    added after `build_artifact_payload` has run — two files with no import
    between them, so pin the name from both ends."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    template = (repo / "server/valuation/viewer/DealSheet.jsx").read_text(encoding="utf-8")
    server_src = (repo / "server/mcp_server.py").read_text(encoding="utf-8")
    assert "data.export?.bundle_url" in template
    assert 'data["export"] = {"bundle_url": bundle_url}' in server_src


def test_export_ttl_outlives_the_upload_default():
    """Uploads are redeemed by a sandbox immediately; an export link waits on
    a human, so its grant carries its own longer lifetime."""
    tokens = UploadTokenStore(ttl_seconds=60.0)
    token = tokens.mint(user_id=1, user_slug="acme", purpose="export",
                        meta={"kind": "volumes"}, ttl_seconds=24 * 3600)
    grant = tokens.claim(token, purpose="export")
    assert grant is not None and grant.ttl_seconds == 24 * 3600
