-- One address, one account: enforce what every writer already assumes.
--
-- Apply against SUPABASE_DATABASE_URL:
--   psql "$SUPABASE_DATABASE_URL" -f deploy/sql/002-users-email-unique.sql
-- Additive and idempotent — safe to re-run; reversible with DROP INDEX.
--
-- Three paths write platform.users.email and all three already treat it as
-- unique: the site's /api/signup refuses an address that exists (returns
-- already_member), provision_and_send.mjs skips already-provisioned emails,
-- and update_user checks email_owner() before attaching. That check is a
-- read-then-write, so two concurrent claims of one address could both pass
-- it; this index makes the loser fail loudly instead of silently creating a
-- second account on the same inbox — which would split a person's history
-- and make recovery ambiguous.
--
-- Partial (email IS NOT NULL) because anonymous CrudeDoc mints deliberately
-- carry a NULL email and there can be any number of those. On lower(email)
-- to match how both the signup path and update_user compare addresses.
--
-- Verified clean before first apply (2026-08-27): 199 rows, 195 with an
-- email, zero case-insensitive duplicates.

CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_key
    ON platform.users (lower(email))
    WHERE email IS NOT NULL;
