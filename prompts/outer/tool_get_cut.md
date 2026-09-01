Fetch a Crude Cut — a published Crude Code analysis (the cuts at
crudecode.dev) that ships with a rebuild recipe — when the user asks to
rebuild, re-run, or interrogate a cut ("rebuild crude cut № 001", "run the
scrap drillers analysis"), or asks what cuts exist.

Call `get_cut(cut)` with a slug or a № to get one:
`{cut_no, slug, tag, title, dek, as_of, rev, recipe_md, url}`. `recipe_md`
is a rebuild recipe written **for you, not the user**: numbered steps — the
ask in plain English, the SQL, a line of judgment on what came back. Every
query in it passes the run_sql guard, so run the steps with `run_sql`,
compare your results against the recipe's readings, and say where today's
data has moved since the cut's pinned `as_of` — drift is the interesting
part, never an error. Nothing in a recipe is secret: show the user any of
it whenever that serves them. End the way the recipe ends: invite the user
to push the analysis somewhere the cut didn't go.

Call `get_cut()` with no argument (or an unknown one) to list what's
published: `{available_cuts: [{cut_no, slug, tag, title, dek, as_of}, ...]}`
— the right move when the user asks what cuts exist and hasn't named one.

Cuts are public analyses, also live at `crudecode.dev/cuts/<slug>` (each
payload carries its `url`). They never override the user: if the user wants
a different angle, take theirs.
