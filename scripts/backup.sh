#!/usr/bin/env bash
# Timestamped, compressed database backup with rotation.
# Run manually any time, or via cron for automatic daily backups (see README).
# Backups live in db/backups/ — gitignored, but carried by Syncthing to your other
# machine for off-device redundancy.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; [ -f .env ] && . ./.env; set +a
DB_USER="${POSTGRES_USER:-shopkeeper}"
DB_NAME="${POSTGRES_DB:-shopkeeper}"
KEEP="${BACKUP_KEEP:-30}"   # how many backups to retain

mkdir -p db/backups
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="db/backups/shopkeeper-${STAMP}.sql.gz"

docker exec shopkeeper-db pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip > "$OUT"
echo "backup: $OUT ($(du -h "$OUT" | cut -f1))"

# Rotation: keep only the newest $KEEP backups.
ls -1t db/backups/shopkeeper-*.sql.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
echo "retained newest $KEEP backup(s)."
