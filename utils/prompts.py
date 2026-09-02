"""Prompt loader — reads markdown files from the prompts/ directory."""

import os
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load(path: str) -> str:
    """Load a prompt file by relative path, e.g. load("mcp/instructions.md")."""
    return (_DIR / path).read_text().strip()


def chat_mode() -> bool:
    """True when this deployment serves a host that cannot render claude.ai
    artifacts or MCP-app surfaces (`CC_CHAT_MODE=1` in the environment).

    A deployment-wide switch, not per user: the prompt surfaces it changes
    (server instructions, tool descriptions) are composed once at startup.
    Read live rather than cached so tests can flip it with the environment.
    """
    return os.environ.get("CC_CHAT_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def chat_mode_note() -> str:
    """The chat-only-host section appended to every prompt surface in chat mode."""
    return load("outer/chat_mode.md")


def tool_doc(path: str) -> str:
    """A tool description: the prompt file, plus the chat-only-host note when
    this deployment runs in chat mode. Appended, never prepended — tool-search
    clients show a description's first sentence until the tool is loaded, and
    that sentence carries the routing keywords."""
    doc = load(path)
    return f"{doc}\n\n{chat_mode_note()}" if chat_mode() else doc


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
    inline so packaged playbooks are discoverable up front. Treat this whole
    channel as unreliable: we observed claude.ai truncating server
    instructions at ~2.3 KB (July 2026), and external reports
    (anthropics/claude-ai-mcp#131) say claude.ai may drop the instructions
    field entirely. Hence system_prompt.md keeps its skill-routing section
    inside the first ~2 KB (insurance against the truncate case), the DB
    schema is deliberately NOT here, and nothing load-bearing may live only
    in this channel. Tool descriptions are the reliable surface — verified
    arriving intact to ~18 KB (Aug 2026) — but tool-search clients defer
    them, showing only each description's FIRST SENTENCE until the model
    loads the tool (search matches full descriptions), so every tool doc's
    opening sentence must carry its routing keywords.
    """
    outer = load("outer/system_prompt.md").rstrip()
    skills = _skills_section()
    skills_block = f"\n\n{skills}" if skills else ""
    chat_block = f"\n\n{chat_mode_note()}" if chat_mode() else ""
    return f"{outer}{skills_block}{chat_block}\n"


def compose_run_sql_doc() -> str:
    """The `run_sql` tool description: usage guidance + the full DB schema.

    The schema lives here — not in the server instructions — because tool
    descriptions are the one prompt surface verified to reach the model
    untruncated. All SQL guidance (tables, columns, join keys, caveats)
    consolidates into this single docstring; other tool docs point here.
    """
    tool = load("outer/tool_run_sql.md").rstrip()
    schema = load("outer/shared_schema.md").strip()
    chat_block = f"\n\n{chat_mode_note()}" if chat_mode() else ""
    return f"{tool}\n\n{schema}{chat_block}\n"
