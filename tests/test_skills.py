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
    # the three bundled files are present, SKILL.md is NOT in files
    assert set(bundle["files"]) == {"schema.py", "triage.py", "example.json"}
    assert "SKILL.md" not in bundle["files"]
    assert "ExtractionResult" in bundle["files"]["schema.py"]


def test_load_skill_unknown_raises():
    with pytest.raises(SkillNotFound):
        load_skill("does-not-exist")
