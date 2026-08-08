-- shopkeeper schema v5: one product photo per item.
-- Image bytes live in a SEPARATE table so item-list queries stay lean; items.has_image
-- is a cheap flag the lists can read. Images are stored in the DB so they ride along
-- with backups and the Mac<->Linux dump transfer. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS item_images (
  item_id      bigint PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  data         bytea NOT NULL,
  content_type text  NOT NULL DEFAULT 'image/jpeg',
  updated_at   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE items ADD COLUMN IF NOT EXISTS has_image boolean NOT NULL DEFAULT false;

COMMIT;
