-- shopkeeper schema v10: optional "drink info" for alcohol (wine / beer / spirits).
-- A small, general set that fits most drinks: ABV %, vintage/year, style or
-- varietal (Shiraz / IPA / Whisky), and origin/region. All nullable — only
-- filled for items where it matters. Runs once.

BEGIN;

ALTER TABLE items ADD COLUMN IF NOT EXISTS abv     numeric(4,1);   -- alcohol %, e.g. 14.5
ALTER TABLE items ADD COLUMN IF NOT EXISTS vintage integer;        -- year, e.g. 2022
ALTER TABLE items ADD COLUMN IF NOT EXISTS style   text;           -- varietal / beer style / spirit type
ALTER TABLE items ADD COLUMN IF NOT EXISTS origin  text;           -- region / country

COMMIT;
