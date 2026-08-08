-- shopkeeper schema v3: allow voiding a sale (soft — keeps the record for audit).
-- Idempotent.

BEGIN;

ALTER TABLE sales ADD COLUMN IF NOT EXISTS voided_at timestamptz;

-- Voided sales are excluded from day totals; index helps those queries.
CREATE INDEX IF NOT EXISTS sales_active_idx ON sales (sold_at DESC) WHERE voided_at IS NULL;

COMMIT;
