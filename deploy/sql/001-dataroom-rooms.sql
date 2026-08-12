-- Dataroom capture: platform.dataroom_rooms + room linkage on extractions.
--
-- First DDL tracked in-repo (earlier platform.* tables were created by hand
-- in Supabase). Apply against SUPABASE_DATABASE_URL:
--   psql "$SUPABASE_DATABASE_URL" -f deploy/sql/001-dataroom-rooms.sql
-- Additive and idempotent — safe to re-run.
--
-- One row per captured room zip. Rooms are content-addressed (sha256) and
-- global across users on purpose: a duplicate upload links to the existing
-- row and never re-stores or re-processes. `initial_extraction` is the
-- first extraction ever produced from this room, snapshotted before any
-- user review and never updated afterward — per-user corrections live only
-- on platform.dataroom_extractions rows.

CREATE TABLE IF NOT EXISTS platform.dataroom_rooms (
    room_id                 uuid PRIMARY KEY,
    sha256                  text        NOT NULL,
    size_bytes              bigint,
    label                   text        NOT NULL DEFAULT '',
    storage_key             text,
    uploaded_by_user_id     bigint      NOT NULL,
    upload_complete         boolean     NOT NULL DEFAULT false,
    initial_extraction      jsonb,
    initial_extraction_at   timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now(),
    completed_at            timestamptz
);

-- One *completed* room per content hash; abandoned pending rows may share it.
CREATE UNIQUE INDEX IF NOT EXISTS dataroom_rooms_sha256_complete
    ON platform.dataroom_rooms (sha256) WHERE upload_complete;

ALTER TABLE platform.dataroom_extractions
    ADD COLUMN IF NOT EXISTS room_id uuid;
