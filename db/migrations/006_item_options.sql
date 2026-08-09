-- shopkeeper schema v6: per-item sell options (e.g. beer Cold / Normal / Set of 24).
-- Each option has a name, a price, and an amount = how many units it represents
-- (Cold/Normal = 1, Set = 24) so a future sale can deduct stock correctly. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS item_options (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  item_id    bigint        NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  name       text          NOT NULL,
  price      numeric(12,2) NOT NULL CHECK (price >= 0),
  amount     numeric(14,3) NOT NULL DEFAULT 1 CHECK (amount > 0),
  currency   text          NOT NULL DEFAULT 'USD',
  created_at timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS item_options_item_idx ON item_options (item_id, id);

COMMIT;
