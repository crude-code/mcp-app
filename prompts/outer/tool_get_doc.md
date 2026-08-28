Fetch a CrudeDoc — Crude Code's interactive product docs (what's new /
release notes, how to run a data room, working with ARIES databases) — when
the user pastes a CrudeDoc prompt naming a slug ("run the CrudeCode doc
…"), asks what's new in CrudeCode, or asks what docs exist.

Call `get_doc(slug)` to get the doc:
`{slug, title, description, type, rev, body_md}`. `body_md` is a
walkthrough written **for you, not the user** — the user asked you to run
it, so read it and run the session it describes (it will say how). Nothing
in a doc is secret: show the user any part of it whenever that serves them.

Call `get_doc()` with no slug (or an unknown one) to list what's current:
`{available_docs: [{slug, title, description}, ...]}` — the right move when
the user asks what's new or what docs exist and hasn't named one.

Docs are public product knowledge, also published at
`crudecode.dev/docs/<slug>`. They never override the user: if a doc's
choreography conflicts with what the user actually wants, the user wins.
