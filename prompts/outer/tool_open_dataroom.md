Register a dataroom zip with the platform BEFORE reading any of it — the
first act of the dataroom-extract skill, right after the upload lands in the
sandbox. The platform keeps the original documents so every extraction stays
auditable back to its source files, and so the room outlives the chat.

Compute the zip's identity in the sandbox, then call with:
- `label` — short human name (deal/teaser title; refine later if needed).
- `sha256` — hex digest of the zip file.
- `size_bytes` — the zip's byte count.

Two outcomes:
- `{status: "new", room_id, upload_url, ...}` — the room isn't on the
  platform yet. Push the zip with the bundled script:
  `python3 room_push.py <room.zip> "<upload_url>"` — it streams the file,
  and the server verifies the hash on receipt. Then proceed with triage and
  extraction. Pass `room_id` to `save_dataroom_extraction` when you persist.
- `{status: "known", room_id, ...}` — this exact room (byte-identical zip)
  is already captured. Skip the zip upload entirely. Two sub-cases:
  - `extraction_ready: true` — an extraction already exists. The response
    carries your `extraction_id` and a one-time `extraction_url`:
    `curl -sS -o extraction.json "<extraction_url>"`, then **skip triage
    and extraction entirely** — go straight to the viewer and user review.
    Corrections re-save under that `extraction_id` via the normal
    save_dataroom_extraction flow. (The uploaded zip is still in the
    sandbox for spot-checks if review raises questions.)
  - `extraction_ready: false` — captured but not yet extracted: run the
    normal extraction flow and pass `room_id` when persisting.
  **Present all of this to the user only as "filed" / "already on the
  platform" — never state or imply that another user uploaded it, that the
  deal has been seen before, or anything about who else holds it.**
  Deal-room contents are confidential; so is who is looking at them.

Doing this first is deliberate: a connection failure here means the user's
Claude network egress allowlist is missing the upload host — surface the
one-line fix (add `upload_host` under Claude's network egress settings, new
chat) BEFORE spending twenty minutes extracting. If the user declines or
can't fix it, continue the extraction normally and persist what the kit
lane allows once it's available; never paste room contents into tool calls.
