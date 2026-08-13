"""Drift guard for the deal-sheet template fast lane.

The lane spans three layers that never import each other: the server mints
content-addressed URLs (deal-sheet-<sha12>.jsx), the deploy scripts publish
the file under that exact name, and the apex nginx vhost serves the
directory. Pin the shared naming so no layer drifts alone.
"""
import hashlib
import re
from pathlib import Path

from server.valuation import artifact_payload as ap

REPO = Path(__file__).resolve().parents[1]


def test_viewer_sha_is_the_file_bytes_digest():
    assert ap.viewer_sha256() == hashlib.sha256(ap._VIEWER_PATH.read_bytes()).hexdigest()


def test_viewer_url_is_content_addressed(monkeypatch):
    monkeypatch.delenv("CC_TEMPLATE_BASE_URL", raising=False)
    sha = ap.viewer_sha256()
    url = ap.viewer_url(sha)
    assert url == f"https://crudecode.dev/templates/deal-sheet-{sha[:12]}.jsx"
    assert re.fullmatch(r"https://crudecode\.dev/templates/deal-sheet-[0-9a-f]{12}\.jsx", url)


def test_viewer_url_respects_base_override(monkeypatch):
    monkeypatch.setenv("CC_TEMPLATE_BASE_URL", "http://127.0.0.1:8080/templates/")
    sha = ap.viewer_sha256()
    assert ap.viewer_url(sha) == f"http://127.0.0.1:8080/templates/deal-sheet-{sha[:12]}.jsx"


def test_deploy_scripts_publish_the_same_name():
    """Both deploy scripts must hash the same source file with sha256sum,
    truncate to 12 chars, and install as deal-sheet-<sha12>.jsx in the
    directory nginx aliases."""
    for script in ("deploy.sh", "deploy-dev.sh"):
        text = (REPO / script).read_text(encoding="utf-8")
        assert "TEMPLATE_SRC=server/valuation/viewer/DealSheet.jsx" in text, script
        assert "TEMPLATE_DIR=/var/www/cc-templates" in text, script
        assert 'sha256sum "$TEMPLATE_SRC" | cut -c1-12' in text, script
        assert 'deal-sheet-${TEMPLATE_SHA}.jsx' in text, script


def test_apex_vhost_serves_the_publish_directory():
    conf = (REPO / "deploy" / "nginx" / "crudecode-site.conf").read_text(encoding="utf-8")
    assert "location /templates/" in conf
    assert "alias /var/www/cc-templates/;" in conf
