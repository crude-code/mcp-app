"""Release versioning: server and renderer must agree.

A dev -> main merge is a release — the last dev commit bumps
server.mcp_server.__version__ and renderer/package.json's version together,
and main gets a vX.Y.Z tag after the merge. This pins the two strings so
neither is ever bumped alone.
"""
import json
import re
from pathlib import Path

import server.mcp_server as srv

REPO = Path(__file__).resolve().parents[1]


def test_server_and_renderer_versions_agree():
    pkg = json.loads((REPO / "renderer" / "package.json").read_text(encoding="utf-8"))
    assert srv.__version__ == pkg["version"]


def test_version_is_semver_shaped():
    assert re.fullmatch(r"\d+\.\d+\.\d+", srv.__version__)
