---
description: Add a feature or make a change, with ceremony sized to the change
argument-hint: <what you want built>
---

You're adding: **$ARGUMENTS**

The point of this command is near-zero ceremony for patterned work, and a real
gate only when the change earns it. Follow the steps in order.

## 1. Load the house rules
Read `.claude/CONVENTIONS.md` before writing anything. Those are the accumulated
"do it like this" decisions — treat them as binding. If the change touches an
area a convention covers, follow it without being asked.

## 2. Size the change — say it out loud
Classify in one line, then act:
- **Patterned** — it matches a known motion below, or it's a small edit to one
  area → just build it. No plan, no questions.
- **Ambiguous / multi-area / architectural** — touches, say, the econ engine +
  orchestrator + tests at once, or the approach isn't obvious → **stop, enter
  plan mode, propose the approach in a few bullets, and wait for approval**
  before editing a file.

When genuinely unsure which bucket, ask one sentence — "This touches X, Y, Z —
want a plan first, or should I just go?" — then respect the answer.

## 3. Known motions (this repo)
If the ask is one of these, follow the file list — don't rediscover it:

**Add an MCP tool**
1. `server/mcp_server.py` — add the
   `@mcp.tool(description=_load_prompt("outer/tool_<name>.md"))` function.
   Mirror `run_sql`: identity check → do the work → return `_json.dumps(...)`.
2. `prompts/outer/tool_<name>.md` — the guidance Claude reads for the tool.
3. `tests/test_tools_<name>.py`, mirroring `tests/test_tools_run_sql.py`.
   (FastMCP surfaces the tool from the decorator — no separate registration.)

**Add a skill**
1. New `skills/<name>/` folder with a `SKILL.md` (YAML frontmatter
   `name`/`description` + instructions) plus any files it references.
   `server/skills.py` scans the directory — nothing else registers it.
2. Cover it in `tests/test_skills.py`.

**Add an economic parameter**
1. `server/valuation/config.py` — add the field to `EconConfig`. The `ECON`
   singleton is the single source; never hardcode the number at a call site.
2. Thread it through the consumer (`econ.py` / `orchestrator.py`), read as
   `config.ECON.<field>`.
3. Test alongside `tests/test_valuation_config*.py` / `test_valuation_econ.py`.

**Add a map layer**
`server/maps/catalog.py` + `server/maps/hydrate.py`; test in `tests/test_maps_*.py`.

If it's not on this list, it's probably a §2 "ambiguous" — lean toward the gate.

## 4. Build it
Write code that reads like the surrounding file — comment density, naming,
idiom. Add or update the test in the same pass. If you touch a schema, keep
`utils/schemas.py` and `prompts/inner/shared_schema.md` in sync — the
`tests/test_schema_drift.py` guard enforces it.

## 5. Prove it, then hand off
Run the affected tests with `.venv/bin/pytest -q` (never bare `python`). When
green, stop and summarize what changed in one or two lines. **Do not commit or
push here — that's `/ship`'s job.** If the user corrected your approach at any
point, append the rule to `.claude/CONVENTIONS.md` in their words before you
finish.
