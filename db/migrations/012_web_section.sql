-- shopkeeper schema v12: optional publishing section for the public catalogue.
--
-- `label` stays what it always was: a free-text operational note ("NO SELL",
-- "High rarity"). `section` is a separate, controlled value that decides which
-- shelf an item appears on in the published website — so an internal note can
-- never leak onto the public site by accident. NULL = ordinary stock.
-- Idempotent.

BEGIN;

ALTER TABLE items ADD COLUMN IF NOT EXISTS section text;

ALTER TABLE items DROP CONSTRAINT IF EXISTS items_section_chk;
ALTER TABLE items ADD CONSTRAINT items_section_chk CHECK (
  section IS NULL OR section IN ('Special', 'Limited Edition', 'Discontinued', 'New Arrival', 'Rare')
);

-- Index the published shelves; most rows are NULL so keep it partial.
CREATE INDEX IF NOT EXISTS items_section_idx ON items (section) WHERE section IS NOT NULL;

-- One-time backfill from the free-text labels already in use. Only maps the
-- unambiguous ones; "NO SELL" is operational and deliberately not published.
UPDATE items SET section = 'Discontinued'
 WHERE section IS NULL AND lower(coalesce(label, '')) LIKE '%discontinued%';

UPDATE items SET section = 'Rare'
 WHERE section IS NULL AND lower(coalesce(label, '')) ~ 'high rarity|^rare$|\mrare\M';

COMMIT;
