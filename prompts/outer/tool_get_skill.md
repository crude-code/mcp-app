Fetch a packaged Crude Code skill — a set of instructions plus the files that
skill needs — so you can follow it directly in your work.

Call `get_skill(name)` with the skill name to get back a bundle:
`{name, description, instructions, files}`. `instructions` is the skill's
guidance (read it and follow it). `files` is a map of `{filename: contents}`
for the supporting files the instructions reference — write them into your
working/sandbox directory so you can read or run them as the instructions
say.

Call `get_skill()` with no name (or an unknown name) to list what's available:
`{available_skills: [{name, description}, ...]}`.

Available skills:
- **dataroom-extract** — when the user uploads an oil & gas dataroom (an
  acquisition/divestiture package: lease operating statements, check stubs,
  AFEs, production reports, title, division orders, a teaser/overview) and
  wants it turned into structured data for deal valuation, call
  `get_skill("dataroom-extract")` and follow the returned instructions.
