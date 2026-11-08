#!/usr/bin/env bash
# Restore drill: back up, restore into a scratch database, compare row counts and the
# migration version with the live database, then drop the scratch copy. Exit 1 on any mismatch.
set -euo pipefail
scratch="eka_restore_drill"
db() { docker compose exec -T db "$@"; }
snapshot() {
  db psql -U eka -d "$1" -At -c "
    SELECT 'alembic', version_num FROM alembic_version
    UNION ALL SELECT 'documents', count(*)::text FROM documents
    UNION ALL SELECT 'chunks', count(*)::text FROM chunks
    UNION ALL SELECT 'chunks_with_vectors', count(embedding)::text FROM chunks
    UNION ALL SELECT 'conversations', count(*)::text FROM conversations
    UNION ALL SELECT 'messages', count(*)::text FROM messages
    UNION ALL SELECT 'rls_tables', count(*)::text FROM pg_class WHERE relforcerowsecurity
    ORDER BY 1"
}

started=$(date +%s)
dump="$(scripts/db_backup.sh backups | tail -1)"
scripts/db_restore.sh "$dump" "$scratch"
live="$(snapshot eka)"
restored="$(snapshot "$scratch")"
db psql -U eka -d postgres -q -c "DROP DATABASE \"$scratch\" WITH (FORCE)"

echo "table|live|restored"
paste -d'|' <(echo "$live") <(echo "$restored" | cut -d'|' -f2)
if [ "$live" != "$restored" ]; then
  echo "RESTORE DRILL FAILED: contents differ" >&2
  exit 1
fi
echo "RESTORE DRILL PASSED in $(( $(date +%s) - started )) s"
