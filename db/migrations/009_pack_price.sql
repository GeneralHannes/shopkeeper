-- shopkeeper schema v9: add a mid-tier price kind "pack" (a smaller group inside a
-- box, e.g. a 6-pack / sleeve) between retail (single) and wholesale (whole box).
-- prices.kind is just widened; no new table. Runs once.

BEGIN;

ALTER TABLE prices DROP CONSTRAINT IF EXISTS prices_kind_chk;
ALTER TABLE prices ADD  CONSTRAINT prices_kind_chk
  CHECK (kind IN ('retail', 'pack', 'wholesale', 'cost'));

COMMIT;
