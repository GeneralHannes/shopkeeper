#!/usr/bin/env bash
# Install a daily cron job that backs up the database at 21:00 (shop close).
# Idempotent: re-running replaces the existing shopkeeper backup entry.
# Cron is per-machine (not synced), so run this once on each machine.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOUR="${BACKUP_HOUR:-21}"
LINE="0 $HOUR * * * cd '$DIR' && ./scripts/backup.sh >> db/backups/backup.log 2>&1"

( crontab -l 2>/dev/null | grep -vF 'shopkeeper' | grep -v 'scripts/backup.sh' ; echo "$LINE" ) | crontab -
echo "installed daily backup at ${HOUR}:00 —"
echo "  $LINE"
echo "check with: crontab -l"
