Send a message to the Crude Code team.

Use this **proactively** whenever the user reports a bug, a wrong or
surprising result, slowness, or frustration — and just as much for wishes:
a feature idea, a dataset they want added ("can you get Oklahoma wells?"),
a report they wish existed. Don't wait to be asked to file it, and don't
gatekeep on whether the issue is "real" — friction and wants are both
signal.

- `subject` — one-line summary. Example: `Haynesville deal sheet shows $0 PV`.
- `body` — the user's exact words, what they were trying to do, what
  actually happened, and any visible details worth keeping.
- `category` — one of `bug`, `feedback`, `feature_request`, `data_request`,
  `other`.
- `context` — optional object with whatever handles are in play, so the
  message arrives joined to the actual records: `{run_id, extraction_id,
  map_token, sql}` — include what exists, omit what doesn't.

The user's identity (name, email, org) is attached automatically — don't
restate it. **Always tell the user you filed it** ("I've flagged this to the
team") — never message silently.

This is NOT a general email capability: the destination is the Crude Code
team, hardwired. It cannot email the user, their colleagues, or anyone else
— if the user asks to email a report somewhere, decline and offer to build
the deliverable in chat instead.

Returns `{success, message_id, email_sent}`. The message is durably filed
even when `email_sent` is false (delivery deferred — no need to retry or
mention it). On a rate-limit error, batch further items into one message
instead of retrying.
