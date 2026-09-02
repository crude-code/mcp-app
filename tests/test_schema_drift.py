"""Guard: shared_schema.md must list exactly the schemas in utils/schemas.py.

If you add a schema to MAP_SCHEMAS or EXPLORATION_SCHEMAS and forget to
update prompts/outer/shared_schema.md (or vice versa), this fails.

The agent-facing schema reference lives between
`<!-- cc:schemas:start -->` and `<!-- cc:schemas:end -->` in
prompts/outer/shared_schema.md. Each schema is its own bullet of the form
``- `name` — description``. This test extracts the leading backticked
identifier from each bullet and asserts the set matches EXPLORATION_SCHEMAS
(the broader of the two — MAP_SCHEMAS is a subset).
"""

import re
from pathlib import Path

from utils.schemas import EXPLORATION_SCHEMAS, MAP_SCHEMAS

_SHARED_SCHEMA = Path(__file__).resolve().parent.parent / "prompts/outer/shared_schema.md"
_BLOCK_RE = re.compile(
    r"<!-- cc:schemas:start -->\s*(.*?)\s*<!-- cc:schemas:end -->",
    re.DOTALL,
)


def test_map_schemas_subset_of_exploration():
    assert MAP_SCHEMAS.issubset(EXPLORATION_SCHEMAS), (
        "MAP_SCHEMAS must be a subset of EXPLORATION_SCHEMAS"
    )


def test_shared_schema_block_matches_code():
    text = _SHARED_SCHEMA.read_text()
    match = _BLOCK_RE.search(text)
    assert match, (
        "missing <!-- cc:schemas:start --> ... <!-- cc:schemas:end --> block "
        "in prompts/outer/shared_schema.md"
    )
    listed = set(re.findall(r"^- `([a-z_]+)`", match.group(1), re.MULTILINE))
    assert listed == EXPLORATION_SCHEMAS, (
        "schema list in shared_schema.md does not match utils/schemas.py:\n"
        f"  listed in md: {sorted(listed)}\n"
        f"  in code:      {sorted(EXPLORATION_SCHEMAS)}"
    )
