#!/usr/bin/env bash
# Starts the core (fake chat model, the compose default) in its own compose project (eka-e2e), so it never
# touches a developer's data, and waits until it is ready. Used by CI and by hand:
#   ui/e2e/stack.sh up      then  E2E_API_KEY=$(cat ui/e2e/.stack.key) npx playwright test
#   ui/e2e/stack.sh down    removes the project's containers and volumes
set -euo pipefail
cd "$(dirname "$0")/../.."
env_file=ui/e2e/.stack.env
project=eka-e2e

if [ "${1:-up}" = "down" ]; then
  docker compose -p "$project" --env-file "$env_file" down -v
  exit 0
fi

# A fresh password and API key per run; only the key's hash goes to the core.
key="e2e-$(openssl rand -hex 16)"
hash=$(printf '%s' "$key" | sha256sum | cut -d' ' -f1)
cat > "$env_file" <<ENV
EKA_DB_PASSWORD=$(openssl rand -hex 16)
EKA_API_KEYS={"e2e-user": {"sha256": "$hash", "role": "user"}}
ENV
printf '%s' "$key" > ui/e2e/.stack.key

docker compose -p "$project" --env-file "$env_file" up -d --build db migrate api worker
for _ in $(seq 1 90); do
  if curl -fs http://localhost:8000/health/ready > /dev/null; then
    echo "core ready"
    exit 0
  fi
  sleep 2
done
docker compose -p "$project" --env-file "$env_file" logs --tail 50 api
exit 1
