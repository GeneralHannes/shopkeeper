# Load .env as DEFAULTS only. A variable the caller already exported
# (e.g. `POSTGRES_DB=shopkeeper_bench ./scripts/migrate.sh`) must win over
# whatever .env sets for the same name — plain `set -a; . .env; set +a`
# silently clobbers it instead, which is how a "scratch DB" migration once
# landed on the live database. Source this and call load_env instead.
load_env() {
  local file="${1:-.env}"
  [ -f "$file" ] || return 0
  local pre; pre="$(export -p)"
  set -a
  . "$file"
  set +a
  # `declare -x` inside a function is implicitly local — force it global (-gx)
  # or the restore below would silently vanish when this function returns.
  eval "${pre//declare -x/declare -gx}" 2>/dev/null || true
}
