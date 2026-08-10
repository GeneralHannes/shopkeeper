-- shopkeeper schema v8: structured naming — brand + size, in addition to the full name.
-- The naming scheme is: <brand> <filler/option> <size>. `name` stays the canonical
-- full string (used by search, sales, etc.); brand/size are optional display metadata
-- that let the UI colour-code the brand and show the size as a chip. Runs once.

BEGIN;

ALTER TABLE items ADD COLUMN IF NOT EXISTS brand text;
ALTER TABLE items ADD COLUMN IF NOT EXISTS size  text;

COMMIT;
