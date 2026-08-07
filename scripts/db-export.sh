#!/usr/bin/env bash
# Export the shopkeeper database to a portable SQL dump.
# Run this BEFORE switching machines — Syncthing carries db/dumps/shopkeeper.sql across,
# then you run db-import.sh on the other machine.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; [ -f .env ] && . ./.env; set +a
DB_USER="${POSTGRES_USER:-shopkeeper}"
DB_NAME="${POSTGRES_DB:-shopkeeper}"

mkdir -p db/dumps
OUT="db/dumps/shopkeeper.sql"

echo "Exporting '$DB_NAME' from container shopkeeper-db -> $OUT"
docker exec shopkeeper-db pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists > "$OUT"
echo "Done: $(wc -l < "$OUT" | tr -d ' ') lines. Syncthing will carry $OUT to your other machine."
