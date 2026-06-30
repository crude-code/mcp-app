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
    """Outer Claude's system prompt + skills + DB schema + widget palette.

    The orchestrator now authors briefing specs directly, so it gets the
    widget vocabulary inline (moved here from the retired inner-agent
    composition). Schema is inline too, so a lookup is one round-trip. The
    skills catalog is inline so packaged playbooks are discoverable up front.
    """
    outer = load("outer/system_prompt.md").rstrip()
    schema = load("inner/shared_schema.md").strip()
    palette = load("outer/widget_palette.md").strip()
    skills = _skills_section()
    skills_block = f"{skills}\n\n" if skills else ""
    return f"{outer}\n\n{skills_block}## Database schema\n\n{schema}\n\n## Widget palette\n\n{palette}\n"
