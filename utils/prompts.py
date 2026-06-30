"""Prompt loader — reads markdown files from the prompts/ directory."""

from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load(path: str) -> str:
    """Load a prompt file by relative path, e.g. load("mcp/instructions.md")."""
    return (_DIR / path).read_text().strip()


def compose_outer_system_prompt() -> str:
    """Outer Claude's system prompt + DB schema + widget palette.

    The orchestrator now authors briefing specs directly, so it gets the
    widget vocabulary inline (moved here from the retired inner-agent
    composition). Schema is inline too, so a lookup is one round-trip.
    """
    outer = load("outer/system_prompt.md").rstrip()
    schema = load("inner/shared_schema.md").strip()
    palette = load("outer/widget_palette.md").strip()
    return f"{outer}\n\n## Database schema\n\n{schema}\n\n## Widget palette\n\n{palette}\n"
