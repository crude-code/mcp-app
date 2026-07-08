---
name: deal-sheet
description: Use after run_valuation returns `surface: "deal_sheet_artifact"` — turns its `data` payload into the standard interactive deal-sheet artifact from the frozen template. Do not design a deal sheet by hand.
---

# Deal Sheet

## What you're doing

`run_valuation` handed you `data` — exec facts, an optional net production
series, and the full pre-computed valuation cube. You are building the ONE
standard deliverable from it: a claude.ai artifact using the bundled
**`DealSheet.jsx`** template. The template is finished and frozen; the server
pre-computed every number. Your entire job is three fills and a narration.

## Steps

1. Create a react artifact whose full content is `DealSheet.jsx`, verbatim.
2. At the bottom, fill the three placeholders:
   - `DATA` — the `data` object from the tool result, pasted **verbatim and
     complete**. Do not drop `economics.cube` (it powers the deck/rate
     selectors), do not round or reformat numbers, do not invent fields.
   - `TITLE` — a short deal title; `DATA.facts.area` is usually right.
   - `TLDR` — 1–2 sentences in your own words: what the deal is and what
     drives the value. This is the only prose you author inside the artifact.
3. In chat, narrate the result from `data.economics.npv_at_centers` (total and
   by-status) — the artifact shows the numbers, you provide the judgment.

## Rules

- **Never** rebuild, restructure, or restyle the component. If the user asks
  for a different look, edit only the `C` palette object at the top.
- Dependencies are `react` and `recharts` only — no lucide-react, no Tailwind,
  no CSS variables, no MCP-app/host APIs (`app.callServerTool` does not exist
  in the artifact sandbox).
- If `DATA.production` is `null`, the template hides the forecast chart on its
  own — don't remove the section or fabricate a series.
- Re-running the valuation (new assumptions) means a fresh `data` → update the
  artifact's `DATA` and nothing else.
