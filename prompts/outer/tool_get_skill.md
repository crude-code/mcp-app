Fetch a packaged Crude Code skill — a set of instructions plus the files that
skill needs — so you can follow it directly in your work.

Call `get_skill(name)` with the skill name to get back a bundle:
`{name, description, instructions, files, file_urls, file_sha256}`.
`instructions` is the skill's guidance (read it and follow it). The
supporting files the instructions reference reach you two ways — take the
cheap one:

1. **Fast lane — download them (whenever you have code execution).** Each
   entry in `file_urls` is the identical file published as a static
   content-addressed URL on `crudecode.dev`. Fetch every file in one pass —
   `curl -fsS --max-time 10 -o <filename> "<url>"` — then verify each
   against `file_sha256` with `sha256sum`. Never re-type file contents from
   the tool response: several bundle files are frozen or drift-tested
   against the server, and a hand-copied byte is a corrupted contract even
   when it looks harmless. On ANY failure (egress 403, 404, timeout, sha
   mismatch, no code execution), silently fall back to lane 2 for that file.
2. **Fallback — write them from context.** `files` is a map of
   `{filename: contents}`; write each into your working/sandbox directory
   **verbatim** — no character normalization, no encoding cleanup (use
   base64 or a quoted heredoc if raw text gives you trouble; never alter
   the bytes to make writing easier).

Call `get_skill()` with no name (or an unknown name) to list what's available:
`{available_skills: [{name, description}, ...]}`.

Available skills:
- **dataroom-extract** — when the user uploads an oil & gas dataroom (an
  acquisition/divestiture package: lease operating statements, check stubs,
  AFEs, production reports, title, division orders, a teaser/overview) and
  wants it turned into structured data for deal valuation, call
  `get_skill("dataroom-extract")` and follow the returned instructions.
- **well-forecasting** — before forecasting any wells for a deal or
  valuation (`forecast_wells`), call `get_skill("well-forecasting")` and
  follow the returned procedure: how to read production history, judge the
  evidence, assert decline parameters and timing, and interrogate the
  consequence echo.
