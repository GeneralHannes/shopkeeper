-- shopkeeper schema v7: allow MULTIPLE photos per item (was exactly one).
-- Give each image its own id and a `sort` order; existing single images become the
-- first photo of their item (sort 0). items.has_image stays a cheap "any photo?" flag
-- the lists read. Runs once (schema_migrations tracks it).

BEGIN;

-- own identity per image + display order
ALTER TABLE item_images ADD COLUMN IF NOT EXISTS id   bigint GENERATED ALWAYS AS IDENTITY;
ALTER TABLE item_images ADD COLUMN IF NOT EXISTS sort integer NOT NULL DEFAULT 0;

-- move the primary key from item_id (one-per-item) to id (many-per-item)
ALTER TABLE item_images DROP CONSTRAINT IF EXISTS item_images_pkey;
ALTER TABLE item_images ADD  CONSTRAINT item_images_pkey PRIMARY KEY (id);

-- fast lookup of an item's photos in order
CREATE INDEX IF NOT EXISTS item_images_item_idx ON item_images (item_id, sort, id);

COMMIT;
