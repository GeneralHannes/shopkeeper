-- shopkeeper schema v2: aliases + fuzzy name matching
-- "coke" -> "Coca-Cola" (alias); "cocacola"/typos -> nearest item (trigram similarity).
-- Idempotent: safe to re-run.

BEGIN;

-- Trigram similarity for fuzzy matching.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Alternate names / nicknames for an item.
CREATE TABLE IF NOT EXISTS item_aliases (
  id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  item_id bigint NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  alias   text   NOT NULL
);

-- One alias per item (case-insensitive).
CREATE UNIQUE INDEX IF NOT EXISTS item_aliases_uq
  ON item_aliases (item_id, lower(alias));

-- Trigram indexes so fuzzy search stays fast as the catalogue grows.
CREATE INDEX IF NOT EXISTS item_aliases_trgm
  ON item_aliases USING gin (lower(alias) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS items_name_trgm
  ON items USING gin (lower(name) gin_trgm_ops);

COMMIT;
