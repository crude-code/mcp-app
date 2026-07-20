"""Skill catalog + bundle loader.

A *skill* is a subfolder of the repo-root ``skills/`` directory containing a
``SKILL.md`` with YAML-ish frontmatter (``name`` / ``description``). This
module is pure: it only reads static files, with no DB / network / identity,
so it works even when ``EI_DB_URL`` is unset.

``list_skills()`` returns the catalog; ``load_skill(name)`` returns the full
bundle (the SKILL.md text plus every other file in the folder as text).
"""

from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


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
    skipped: list[str] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.name == "SKILL.md":
            continue
        try:
            files[path.name] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            skipped.append(path.name)

    bundle = {
        "name": fm.get("name") or name,
        "description": fm.get("description", ""),
        "instructions": instructions,
        "files": files,
    }
    if skipped:
        bundle["skipped_files"] = skipped
    return bundle
