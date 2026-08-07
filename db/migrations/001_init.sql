-- shopkeeper schema v1
-- Family-shop inventory + point-of-sale. Prices stored as numeric with a default currency.
-- Runs automatically on first `docker compose up` (mounted into docker-entrypoint-initdb.d).

BEGIN;

-- Auto-touch updated_at on UPDATE.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- items: the goods on the shelves
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS items (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name             text          NOT NULL,
  sku              text          UNIQUE,
  barcode          text          UNIQUE,
  category         text,
  unit             text          NOT NULL DEFAULT 'each',   -- each, kg, litre, pack...
  quantity_on_hand numeric(14,3) NOT NULL DEFAULT 0,
  active           boolean       NOT NULL DEFAULT true,
  note             text,
  created_at       timestamptz   NOT NULL DEFAULT now(),
  updated_at       timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS items_name_idx   ON items (lower(name));
CREATE INDEX IF NOT EXISTS items_active_idx ON items (active);

DROP TRIGGER IF EXISTS items_touch ON items;
CREATE TRIGGER items_touch BEFORE UPDATE ON items
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- prices: history-preserving. Current price = latest effective_from per item.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prices (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  item_id        bigint        NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  price          numeric(12,2) NOT NULL CHECK (price >= 0),
  currency       text          NOT NULL DEFAULT 'USD',
  effective_from timestamptz   NOT NULL DEFAULT now(),
  note           text
);
CREATE INDEX IF NOT EXISTS prices_item_effective_idx ON prices (item_id, effective_from DESC);

-- Convenience: the current price per item.
CREATE OR REPLACE VIEW item_current_price AS
SELECT DISTINCT ON (p.item_id)
       p.item_id, p.price, p.currency, p.effective_from
FROM prices p
ORDER BY p.item_id, p.effective_from DESC;

-- ---------------------------------------------------------------------------
-- sales + sale_lines: the cashier record
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sales (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sold_at        timestamptz   NOT NULL DEFAULT now(),
  total          numeric(12,2) NOT NULL DEFAULT 0 CHECK (total >= 0),
  currency       text          NOT NULL DEFAULT 'USD',
  payment_method text,                                       -- cash, card, ...
  note           text
);
CREATE INDEX IF NOT EXISTS sales_sold_at_idx ON sales (sold_at DESC);

-- item_id nullable so ad-hoc / custom lines are allowed; description snapshots what was sold.
CREATE TABLE IF NOT EXISTS sale_lines (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sale_id     bigint        NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  item_id     bigint        REFERENCES items(id) ON DELETE SET NULL,
  description text          NOT NULL,
  quantity    numeric(14,3) NOT NULL DEFAULT 1 CHECK (quantity > 0),
  unit_price  numeric(12,2) NOT NULL CHECK (unit_price >= 0),
  line_total  numeric(12,2) NOT NULL CHECK (line_total >= 0)
);
CREATE INDEX IF NOT EXISTS sale_lines_sale_idx ON sale_lines (sale_id);
CREATE INDEX IF NOT EXISTS sale_lines_item_idx ON sale_lines (item_id);

-- ---------------------------------------------------------------------------
-- stock_movements: append-only ledger of every quantity change (audit trail)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_movements (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  item_id    bigint        NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  change     numeric(14,3) NOT NULL,                         -- +restock, -sale, +/-adjustment
  reason     text          NOT NULL,                         -- sale, restock, adjustment, correction
  ref        text,                                           -- e.g. 'sale:123'
  created_at timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stock_movements_item_idx ON stock_movements (item_id, created_at DESC);

COMMIT;
