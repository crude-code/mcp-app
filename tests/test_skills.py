"""Tests for server/skills.py — the skill catalog + bundle loader."""

import pytest

from server.skills import (
    SkillNotFound,
    list_skills,
    load_skill,
    parse_frontmatter,
)


def test_parse_frontmatter_reads_name_and_description():
    text = "---\nname: foo\ndescription: Use when bar.\n---\n\n# Body\n"
    fm = parse_frontmatter(text)
    assert fm["name"] == "foo"
    assert fm["description"] == "Use when bar."


def test_parse_frontmatter_no_block_returns_empty():
    assert parse_frontmatter("# Just a heading\n") == {}


def test_list_skills_includes_dataroom_extract():
    skills = list_skills()
    names = [s["name"] for s in skills]
    assert "dataroom-extract" in names
    entry = next(s for s in skills if s["name"] == "dataroom-extract")
    assert "dataroom" in entry["description"].lower()


def test_load_skill_returns_instructions_and_files():
    bundle = load_skill("dataroom-extract")
    assert bundle["name"] == "dataroom-extract"
    assert "dataroom" in bundle["description"].lower()
    # instructions is the SKILL.md body text
    assert "# Dataroom Extract" in bundle["instructions"]
    # the bundled files are present, SKILL.md is NOT in files
    assert set(bundle["files"]) == {"schema.py", "triage.py", "example.json",
                                    "DataroomViewer.jsx", "persist_pack.py",
                                    "room_push.py", "viewer_payload.py"}
    assert "SKILL.md" not in bundle["files"]
    assert "ExtractionResult" in bundle["files"]["schema.py"]


def test_load_skill_unknown_raises():
    with pytest.raises(SkillNotFound):
        load_skill("does-not-exist")


import json

from server.mcp_server import get_skill


def _call(fn):
    """get_skill is registered as a FastMCP tool; unwrap to the plain fn if needed."""
    return getattr(fn, "fn", fn)


def test_get_skill_tool_returns_bundle_json():
    out = json.loads(_call(get_skill)("dataroom-extract"))
    assert out["name"] == "dataroom-extract"
    assert "# Dataroom Extract" in out["instructions"]
    assert "schema.py" in out["files"]


def test_get_skill_tool_no_name_returns_catalog():
    out = json.loads(_call(get_skill)(""))
    names = [s["name"] for s in out["available_skills"]]
    assert "dataroom-extract" in names


def test_get_skill_tool_unknown_name_returns_catalog():
    out = json.loads(_call(get_skill)("nope"))
    assert "available_skills" in out
    names = [s["name"] for s in out["available_skills"]]
    assert "dataroom-extract" in names
