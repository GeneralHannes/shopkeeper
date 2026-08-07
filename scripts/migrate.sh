#!/usr/bin/env bash
# Apply all db/migrations/*.sql in order. Every migration is idempotent, so this
# is safe to re-run and safe on a fresh database. (On a brand-new DB, Postgres also
# auto-runs these once via docker-entrypoint-initdb.d; this script is for upgrades.)
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; [ -f .env ] && . ./.env; set +a
DB_USER="${POSTGRES_USER:-shopkeeper}"
DB_NAME="${POSTGRES_DB:-shopkeeper}"

for f in db/migrations/*.sql; do
  echo "applying $(basename "$f")"
  docker exec -i shopkeeper-db psql -q -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" < "$f"
done
echo "migrations applied."
