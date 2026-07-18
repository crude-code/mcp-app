# Conventions — how we do it here

The accumulated "no, do it like this" decisions. Every entry is a rule the verbs
(`/add-feature`, `/debug`, `/refactor`, …) should follow without being reminded.

**When the user corrects an approach, capture the rule here in their words.**
That's how this file grows — and it's what lets an unattended weekend session
work the way they would, without them watching.

## Python
- Always `.venv/bin/python` / `.venv/bin/pytest`. Never bare `python` / `python3`.
- `config.ECON` is the single source for every economic parameter. Read as
  `config.ECON.<field>`; never re-hardcode a number at a call site.

## Structure
- One React component per `PascalCase.tsx`; `kebab-case.tsx` is an entry
  bootstrap only.
- A new skill is just a `skills/<name>/SKILL.md` folder — the scanner picks it
  up, nothing else registers it. Same idea for tools: the `@mcp.tool` decorator
  *is* the registration.

## Renderer styling
- Color / type / design tokens via inline `style={{}}` with semantic CSS vars
  (`var(--bg-surface)`, `var(--text-primary)`, `var(--content-accent)`, …).
  Layout (flex, grid, padding, gap, sizing) via Tailwind classes.
- Never shadcn-style tokens (`bg-card`, `text-foreground`). `src/index.css` is
  the single source of truth for color, type, and surface identity.

## Tests & docs
- Touch a schema → keep `utils/schemas.py` and `prompts/inner/shared_schema.md`
  in sync; `tests/test_schema_drift.py` guards this.
- The frozen artifact templates (`server/valuation/viewer/DealSheet.jsx`, map
  viewers) run in the claude.ai artifact sandbox — react + recharts only, no
  host APIs, no CSS vars.

---
_Add new rules below as they come up._
