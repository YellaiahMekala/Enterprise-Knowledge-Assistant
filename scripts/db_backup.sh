#!/usr/bin/env bash
# Back up the Compose database: roles (needed by the row-level security policies) and a
# custom-format dump. Usage: scripts/db_backup.sh [out_dir]   (default: backups/)
set -euo pipefail
out="${1:-backups}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$out"
db() { docker compose exec -T db "$@"; }

# Role definitions only; passwords are excluded so the file holds no secrets.
db pg_dumpall -U eka --roles-only --no-role-passwords > "$out/eka-$stamp.roles.sql"
db pg_dump -U eka -d eka -Fc > "$out/eka-$stamp.dump"
db pg_restore --list < "$out/eka-$stamp.dump" > /dev/null   # fails on a truncated dump

ls -l "$out/eka-$stamp".*
echo "$out/eka-$stamp.dump"
