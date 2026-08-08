#!/usr/bin/env bash
# Restore the database from a backup. With no argument, restores the newest backup.
# WARNING: this REPLACES current data (the dump drops & recreates objects first).
#
#   ./scripts/restore.sh                       # newest backup
#   ./scripts/restore.sh db/backups/xxx.sql.gz # a specific one
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; [ -f .env ] && . ./.env; set +a
DB_USER="${POSTGRES_USER:-shopkeeper}"
DB_NAME="${POSTGRES_DB:-shopkeeper}"

FILE="${1:-$(ls -1t db/backups/shopkeeper-*.sql.gz 2>/dev/null | head -1 || true)}"
if [ -z "${FILE:-}" ] || [ ! -f "$FILE" ]; then
  echo "no backup file found (looked in db/backups/). pass one explicitly?"
  exit 1
fi

echo "restoring from $FILE"
echo "  -> this REPLACES the current contents of '$DB_NAME'. Ctrl-C now to abort."
sleep 2
gunzip -c "$FILE" | docker exec -i shopkeeper-db psql -q -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME"
echo "restored from $(basename "$FILE")."
