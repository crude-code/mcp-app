Persist a dataroom extraction to the platform so the deal record outlives the
chat. Call this only with an `ExtractionResult` produced by following the
`dataroom-extract` skill — never for ad-hoc JSON you assembled some other way.

- `extraction` — the full `extraction.json` object, verbatim. Don't trim,
  summarize, or re-shape it; the stored copy is the audit record.
- `label` — a short human name for the room (e.g. `"Bison Whitetail — Weld Co
  NPRI"`). Use the deal/teaser title when there is one.
- `extraction_id` — omit on first save. Pass the id you got back only when
  re-saving the *same* room after corrections (the user caught something in
  the viewer, you re-extracted a file, etc.) so the stored copy is updated in
  place instead of duplicated.

Returns `{extraction_id, label, saved: true}` — mention the id in chat so the
record is traceable, then carry on. On `{error}`, tell the user persistence
failed and continue the workflow; never block the extraction or valuation on a
failed save, and never retry more than once.
