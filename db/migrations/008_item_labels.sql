-- shopkeeper schema v8: optional prominent operational label for an item.
BEGIN;

ALTER TABLE items ADD COLUMN IF NOT EXISTS label text;

COMMIT;
