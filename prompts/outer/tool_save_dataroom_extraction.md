Persist a dataroom extraction to the platform so the deal record outlives the
chat. Call this only with the kit printed by `persist_pack.py` (bundled with
the `dataroom-extract` skill) — run the packer, copy its fields into this
call verbatim. Never hand-assemble the arguments and never send an
abbreviated or "representative" copy: the sandbox file dies with the session,
and this stored copy is the only durable record.

What the platform keeps is the room's **private economics** — the interests,
the realized prices / taxes / deductions from check stubs, the LOS/AFE
expenses — plus the deal, wells, tracts, division orders, and document
inventory. Production history is omitted by default (public state data
already covers API'd wells); the packer's `--with-production` flag exists for
name-only wells, uncovered states, or NGL detail.

Arguments (each maps 1:1 to a field the packer prints):
- `extraction` — the packer's slim `ExtractionResult` (bulk arrays emptied).
- `revenue_csv` / `production_csv` — the packed tall tables. The server
  expands them back into canonical rows with full provenance before storing;
  CSV exists only on the wire.
- `sources` — the packer's provenance legend.
- `label` — short human name for the room; use the deal/teaser title.
- `extraction_id` — omit on first save. Pass the id you got back only when
  re-saving the *same* room (corrections after review, or a count mismatch)
  so the row is updated in place, not duplicated.

Returns `{extraction_id, label, saved: true, stored: {…}}`. **Compare
`stored` to the packer's `expected_stored` counts** — any shortfall means
rows were lost in transit: re-call with the same `extraction_id` until they
match. Mention the id in chat so the record is traceable. On `{error}`
(row-precise for CSV problems), fix the kit and re-call once; if it still
fails, tell the user and continue the workflow — never block the extraction
or valuation on persistence.
