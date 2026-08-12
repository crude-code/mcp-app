Persist a dataroom extraction to the platform so the deal record outlives the
chat. This tool moves no data itself: it returns a **one-time upload URL**,
and the bundled `persist_pack.py` (dataroom-extract skill) POSTs the kit to
it directly from the sandbox — the extraction never passes through the chat.
Never paste extraction contents, CSV tables, or the kit into any tool call.

Flow (the skill walks you through it):
1. Call this tool with a `label` (short human name — the deal/teaser title).
   It returns `{upload_url, upload_host, expires_in_seconds, how}`.
2. Run: `python3 persist_pack.py extraction.json --upload "<upload_url>"`
   (add `--with-production` per the skill's production policy).
3. The script uploads, verifies the server's stored counts against its own
   `expected_stored`, and prints a one-line verdict. `{"saved": true,
   "verified": true, "extraction_id": ...}` means done — mention the
   extraction_id in chat so the record is traceable.

Arguments:
- `label` — required. Short human name for the room.
- `extraction_id` — omit on first save. Pass the id you got back only when
  re-saving the *same* room (corrections after review), so the row is
  updated in place, not duplicated. Re-run the packer first; mint a fresh
  URL each time (URLs are single-use).

Failure handling:
- The URL expires in ~15 minutes and dies when used — a stale or spent URL
  is fixed by calling this tool again (cheap).
- `verified: false` in the verdict: mint a fresh URL with the returned
  extraction_id and re-upload.
- A **connection error** from the script means the sandbox cannot reach
  `upload_host`: the user's Claude network egress allowlist is missing it.
  Tell the user, in plain language, to add that exact host under Claude's
  network egress settings (Settings → Capabilities on individual plans;
  their workspace admin on Team/Enterprise), then continue in a new chat.
  This is incomplete setup, not a degraded mode — do NOT fall back to
  pasting extraction data into tool calls, and never block the viewer or
  the rest of the session on it.
