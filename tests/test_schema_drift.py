"""Guard: shared_schema.md must list exactly the schemas in utils/schemas.py.

If you add a schema to WIDGET_SCHEMAS or EXPLORATION_SCHEMAS and forget to
update prompts/outer/shared_schema.md (or vice versa), this fails.

The agent-facing schema reference lives between
`<!-- ei:schemas:start -->` and `<!-- ei:schemas:end -->` in
prompts/outer/shared_schema.md. Each schema is its own bullet of the form
``- `name` — description``. This test extracts the leading backticked
identifier from each bullet and asserts the set matches EXPLORATION_SCHEMAS
(the broader of the two — WIDGET_SCHEMAS is a documented subset).
"""

import re
from pathlib import Path

from utils.schemas import EXPLORATION_SCHEMAS, WIDGET_SCHEMAS

_SHARED_SCHEMA = Path(__file__).resolve().parent.parent / "prompts/outer/shared_schema.md"
_BLOCK_RE = re.compile(
    r"<!-- ei:schemas:start -->\s*(.*?)\s*<!-- ei:schemas:end -->",
    re.DOTALL,
)


def test_widget_schemas_subset_of_exploration():
    assert WIDGET_SCHEMAS.issubset(EXPLORATION_SCHEMAS), (
        "WIDGET_SCHEMAS must be a subset of EXPLORATION_SCHEMAS"
    )


def test_shared_schema_block_matches_code():
    text = _SHARED_SCHEMA.read_text()
    match = _BLOCK_RE.search(text)
    assert match, (
        "missing <!-- ei:schemas:start --> ... <!-- ei:schemas:end --> block "
        "in prompts/outer/shared_schema.md"
    )
    listed = set(re.findall(r"^- `([a-z_]+)`", match.group(1), re.MULTILINE))
    assert listed == EXPLORATION_SCHEMAS, (
        "schema list in shared_schema.md does not match utils/schemas.py:\n"
        f"  listed in md: {sorted(listed)}\n"
        f"  in code:      {sorted(EXPLORATION_SCHEMAS)}"
    )
