"""End-to-end guarantee for the persist kit: what persist_pack.py prints,
extraction_transport.py must expand back to the original rows — and what
--upload POSTs must be that same kit, verified against the server's stored
echo. Runs the packer as a subprocess (the way the sandbox does) against the
skill's bundled example.json."""
import importlib.util
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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


def _run_pack_raw(*flags):
    """Like _run_pack but tolerates nonzero exits (upload failure paths)."""
    proc = subprocess.run(
        [sys.executable, str(_PACK), str(_EXAMPLE), *flags],
        capture_output=True, text=True,
    )
    return proc.returncode, json.loads(proc.stdout)


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


# ── --upload mode ────────────────────────────────────────────────────────────

class _UploadHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.received.append((self.path, json.loads(body)))
        status, payload = self.server.reply
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):     # keep pytest output clean
        pass


@pytest.fixture
def upload_server():
    server = HTTPServer(("127.0.0.1", 0), _UploadHandler)
    server.received = []
    server.reply = (200, {})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def _url(server):
    return f"http://127.0.0.1:{server.server_address[1]}/upload/kit/tok"


def test_upload_posts_kit_and_verifies(upload_server):
    expected = _run_pack()["expected_stored"]
    upload_server.reply = (200, {"extraction_id": "id-1", "label": "Room",
                                 "saved": True, "stored": expected})
    code, verdict = _run_pack_raw("--upload", _url(upload_server))
    assert code == 0
    assert verdict["saved"] is True and verdict["verified"] is True
    assert verdict["extraction_id"] == "id-1"
    path, posted = upload_server.received[0]
    assert path == "/upload/kit/tok"
    # the wire kit is exactly the transport fields — no counts, no extras
    assert set(posted) == {"extraction", "revenue_csv", "production_csv", "sources"}
    assert posted["extraction"]["revenue_observations"] == []


def test_upload_flags_stored_shortfall(upload_server):
    expected = _run_pack()["expected_stored"]
    short = dict(expected, revenue_observations=0)
    upload_server.reply = (200, {"extraction_id": "id-1", "saved": True,
                                 "stored": short})
    code, verdict = _run_pack_raw("--upload", _url(upload_server))
    assert code == 1
    assert verdict["saved"] is True and verdict["verified"] is False
    assert verdict["expected_stored"] == expected


def test_upload_surfaces_http_error_body(upload_server):
    upload_server.reply = (422, {"error": "revenue_csv line 3: src '9' not in sources legend"})
    code, verdict = _run_pack_raw("--upload", _url(upload_server))
    assert code == 1
    assert verdict["saved"] is False
    assert verdict["status"] == 422
    assert "not in sources legend" in verdict["error"]


def test_upload_connection_failure_prints_allowlist_hint():
    # port 9 (discard) is closed on any sane box — connection refused, fast
    code, verdict = _run_pack_raw("--upload", "http://127.0.0.1:9/upload/kit/tok")
    assert code == 1
    assert verdict["saved"] is False
    assert "network" in verdict["hint"]
    assert "allowlist" in verdict["hint"]
