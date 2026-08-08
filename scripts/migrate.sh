#!/usr/bin/env bash
# Apply db/migrations/*.sql that haven't run yet, tracked in a schema_migrations table
# so each file runs exactly once (safe to re-run; safe on a fresh database).
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; [ -f .env ] && . ./.env; set +a
DB_USER="${POSTGRES_USER:-shopkeeper}"
DB_NAME="${POSTGRES_DB:-shopkeeper}"

run() { docker exec -i shopkeeper-db psql -q -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" "$@"; }

run -c "CREATE TABLE IF NOT EXISTS schema_migrations (filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());"

for f in db/migrations/*.sql; do
  name="$(basename "$f")"
  applied="$(run -tAc "SELECT 1 FROM schema_migrations WHERE filename = '$name'")"
  if [ "$applied" = "1" ]; then
    echo "skip  $name"
    continue
  fi
  echo "apply $name"
  run < "$f"
  run -c "INSERT INTO schema_migrations (filename) VALUES ('$name')"
done
echo "migrations up to date."
