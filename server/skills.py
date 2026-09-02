"""Skill catalog + bundle loader.

A *skill* is a subfolder of the repo-root ``skills/`` directory containing a
``SKILL.md`` with YAML-ish frontmatter (``name`` / ``description``). This
module is pure: it only reads static files, with no DB / network / identity,
so it works even when ``CC_DB_URL`` is unset.

``list_skills()`` returns the catalog; ``load_skill(name)`` returns the full
bundle (the SKILL.md text plus every other file in the folder as text) —
plus, per supporting file, a content-addressed public URL and sha256. The
deploy scripts publish every supporting file as ``skill-<sha12>-<name>`` on
the apex (same lane and same rationale as the deal-sheet template: a session
with code execution downloads the frozen file instead of re-emitting it
token by token, and the inline text stays the universal fallback). Naming is
pinned against the deploy scripts by tests/test_template_publish_drift.py.
"""

import hashlib
import os
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# Where the deploy scripts publish every frozen file — skill supporting files
# here, the deal-sheet template in server/valuation/artifact_payload.py — as
# static, content-addressed copies. Served from the apex on purpose: sandbox
# egress allowlists that cover crudecode.dev don't extend to the mcp
# subdomains. CC_TEMPLATE_BASE_URL overrides the base for local testing.
_DEFAULT_TEMPLATE_BASE = "https://crudecode.dev/templates"


def template_base_url() -> str:
    return os.environ.get("CC_TEMPLATE_BASE_URL", _DEFAULT_TEMPLATE_BASE).rstrip("/")


def _published_file_url(filename: str, sha256_hex: str) -> str:
    return f"{template_base_url()}/skill-{sha256_hex[:12]}-{filename}"


class SkillNotFound(Exception):
    """Raised when no skill folder with a SKILL.md matches the given name."""


def parse_frontmatter(text: str) -> dict:
    """Parse a leading ``--- ... ---`` block into a dict of key: value.

    Minimal by design: one ``key: value`` per line, value is everything after
    the first colon (stripped). Returns ``{}`` when there is no frontmatter
    block. Good enough for the simple name/description blocks skills carry; do
    not grow this into a general YAML parser.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()
    return fm


def _skill_folders() -> list[Path]:
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(
        p for p in SKILLS_DIR.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    )


def list_skills() -> list[dict]:
    """Catalog of available skills: ``[{"name", "description"}, ...]``."""
    catalog = []
    for folder in _skill_folders():
        fm = parse_frontmatter((folder / "SKILL.md").read_text(encoding="utf-8"))
        catalog.append({
            "name": fm.get("name") or folder.name,
            "description": fm.get("description", ""),
        })
    return sorted(catalog, key=lambda s: s["name"])


def load_skill(name: str) -> dict:
    """Full bundle for ``name``: instructions (SKILL.md) + sibling files as text.

    Raises ``SkillNotFound`` if no matching skill folder exists.
    """
    folder = SKILLS_DIR / name
    skill_md = folder / "SKILL.md"
    if not skill_md.is_file():
        raise SkillNotFound(name)

    instructions = skill_md.read_text(encoding="utf-8")
    fm = parse_frontmatter(instructions)

    files: dict = {}
    file_urls: dict = {}
    file_sha256: dict = {}
    skipped: list[str] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.name == "SKILL.md":
            continue
        try:
            files[path.name] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            skipped.append(path.name)
            continue
        # Digest the raw bytes — must equal `sha256sum` on the published
        # copy so a fetching session can verify before trusting the file.
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        file_sha256[path.name] = digest
        file_urls[path.name] = _published_file_url(path.name, digest)

    bundle = {
        "name": fm.get("name") or name,
        "description": fm.get("description", ""),
        "instructions": instructions,
        "files": files,
        "file_urls": file_urls,
        "file_sha256": file_sha256,
    }
    if skipped:
        bundle["skipped_files"] = skipped
    return bundle
