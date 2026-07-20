Forecast a set of wells. Group them by area/geography: each group is the wells in
that area plus the analog wells you judge represent it.

Pass `groups`: a list of `{area, wells, analogs}`.
- `area` — a short label for the area (e.g. "Campbell Co · Niobrara B").
- `wells` — all the subject wells in that area (producing AND non-producing,
  mixed; don't pre-sort them).
- `analogs` — wells you pick that represent the area. Supply them whenever a
  group has wells that are undrilled, early, or otherwise can't stand on their own
  production. Omit only when every well in the group is a long-term producer.

The server classifies each well by its own production (long-history producers fit
their own decline; thin/early producers keep their real peak but borrow the
analogs' decline shape; undrilled wells use the analogs outright) and returns, per
area, the wells bucketed by status (PDP/DUC/PUD), the classification spectrum, and
analog fit stats. Carry the returned `run_id` into `run_valuation`.

If it returns `analogs_required`, some wells need analogs you didn't supply —
explore with `run_sql` for comparable wells (same formation, similar lateral,
nearby, enough history) and call again with them in the right group. Nothing is
saved on a bounce.
