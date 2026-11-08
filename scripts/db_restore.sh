#!/usr/bin/env bash
# Restore a dump made by db_backup.sh into a database of the Compose cluster.
#   scripts/db_restore.sh backups/eka-<stamp>.dump [target_db]   (default target: eka)
# Restoring over "eka" replaces its contents: stop the api and worker first.
set -euo pipefail
dump="$1"
target="${2:-eka}"
roles="${dump%.dump}.roles.sql"
db() { docker compose exec -T db "$@"; }

if [ -f "$roles" ]; then
  # Existing roles report "already exists"; that is expected on the same cluster.
  db psql -U eka -d postgres -q -v ON_ERROR_STOP=0 < "$roles" > /dev/null 2>&1 || true
fi
db psql -U eka -d postgres -q -c "DROP DATABASE IF EXISTS \"$target\" WITH (FORCE)" \
  -c "CREATE DATABASE \"$target\""
db pg_restore -U eka -d "$target" --no-owner --exit-on-error < "$dump"
echo "restored $dump into $target"
