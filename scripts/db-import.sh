#!/usr/bin/env bash
# Import the portable SQL dump into THIS machine's shopkeeper database.
# Run this AFTER Syncthing has synced, when you arrive on the other machine.
# WARNING: --clean in the dump drops & recreates objects, replacing local data with the dump.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; [ -f .env ] && . ./.env; set +a
DB_USER="${POSTGRES_USER:-shopkeeper}"
DB_NAME="${POSTGRES_DB:-shopkeeper}"

IN="db/dumps/shopkeeper.sql"
[ -f "$IN" ] || { echo "No dump at $IN — nothing to import."; exit 1; }

echo "Importing $IN -> '$DB_NAME' (container shopkeeper-db)"
docker exec -i shopkeeper-db psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" < "$IN"
echo "Done. Local database now matches the dump."
