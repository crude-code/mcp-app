"""Prompt loader — reads markdown files from the prompts/ directory."""

from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load(path: str) -> str:
    """Load a prompt file by relative path, e.g. load("mcp/instructions.md")."""
    return (_DIR / path).read_text().strip()


def _skills_section() -> str:
    """A catalog of skills available via `get_skill`, built live from disk.

    Listed in the always-loaded system prompt so Claude can discover a
    packaged playbook (e.g. dataroom-extract) the moment a matching task
    arrives — rather than only seeing it inside `get_skill`'s deferred,
    truncatable tool docstring. Each skill's frontmatter `description` is the
    trigger; dynamic listing means new skills appear with no prompt edit.
    """
    from server.skills import list_skills  # pure, dependency-free; local import avoids inversion at module load

    skills = list_skills()
    if not skills:
        return ""
    lines = [
        "## Skills",
        "",
        "Some tasks have a packaged playbook behind the `get_skill` tool — the "
        "contract, worked examples, and files the job needs. When a request "
        "matches one of these, call `get_skill(name)` and follow the returned "
        "instructions **before** improvising the workflow by hand. If a task "
        "looks like it might match, probe with `get_skill()` rather than "
        "defaulting to parsing things yourself.",
        "",
    ]
    lines += [f"- **{s['name']}** — {s['description']}" for s in skills]
    return "\n".join(lines)


def compose_outer_system_prompt() -> str:
    """Outer Claude's system prompt + skills catalog.

    The outer prompt frames the artifact-first workflow; the skills catalog is
    inline so packaged playbooks are discoverable up front. The DB schema is
    deliberately NOT here: clients truncate MCP server instructions (observed
    at ~2.3 KB on claude.ai), so anything appended after the opening sections
    never reaches the model. The schema rides in the `run_sql` tool
    description instead (`compose_run_sql_doc`), which arrives intact.
    """
    outer = load("outer/system_prompt.md").rstrip()
    skills = _skills_section()
    skills_block = f"\n\n{skills}" if skills else ""
    return f"{outer}{skills_block}\n"


def compose_run_sql_doc() -> str:
    """The `run_sql` tool description: usage guidance + the full DB schema.

    The schema lives here — not in the server instructions — because tool
    descriptions are the one prompt surface verified to reach the model
    untruncated. All SQL guidance (tables, columns, join keys, caveats)
    consolidates into this single docstring; other tool docs point here.
    """
    tool = load("outer/tool_run_sql.md").rstrip()
    schema = load("outer/shared_schema.md").strip()
    return f"{tool}\n\n{schema}\n"
