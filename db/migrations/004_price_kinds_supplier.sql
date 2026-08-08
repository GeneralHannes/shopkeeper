-- shopkeeper schema v4: multiple price kinds per item + supplier.
--   retail    = single sell price (what a customer pays for one)
--   wholesale = bulk sell price
--   cost      = what you paid the supplier (for profit/margin)
-- Idempotent.

BEGIN;

-- Price kind. Existing rows become 'retail'.
ALTER TABLE prices ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'retail';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'prices_kind_chk') THEN
    ALTER TABLE prices ADD CONSTRAINT prices_kind_chk
      CHECK (kind IN ('retail', 'wholesale', 'cost'));
  END IF;
END $$;

-- Who you buy the item from.
ALTER TABLE items ADD COLUMN IF NOT EXISTS supplier text;

-- Current price is now the latest per (item, kind).
DROP VIEW IF EXISTS item_current_price;
CREATE VIEW item_current_price AS
SELECT DISTINCT ON (p.item_id, p.kind)
       p.item_id, p.kind, p.price, p.currency, p.effective_from
FROM prices p
ORDER BY p.item_id, p.kind, p.effective_from DESC;

CREATE INDEX IF NOT EXISTS prices_item_kind_effective_idx
  ON prices (item_id, kind, effective_from DESC);

COMMIT;
