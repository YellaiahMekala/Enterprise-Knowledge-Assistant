#!/usr/bin/env bash
# Tests scripts/deploy_task_def.jq (the filter in .github/workflows/deploy.yml) on sample
# describe-task-definition output. Needs jq on PATH, or Docker (ghcr.io/jqlang/jq).
set -u
here="$(cd "$(dirname "$0")" && pwd)"
fx="$here/deploy_fixtures"
if command -v jq >/dev/null 2>&1; then
  run() { jq "$@"; }
  FILTER="$here/deploy_task_def.jq"; IN="$fx"
else
  run() { MSYS_NO_PATHCONV=1 docker run -i --rm -v "$here:/w:ro" -w /w ghcr.io/jqlang/jq:1.7.1 "$@"; }
  FILTER="deploy_task_def.jq"; IN="deploy_fixtures"
fi
ARGS=(--arg core "core.example/eka-core:abc123" --arg edge "edge.example/eka-edge:abc123" --arg agent "agent.example/eka-ops-agent:abc123")
fail=0
check() { if [ "$2" = "ok" ]; then echo "PASS $1"; else echo "FAIL $1: $2"; fail=1; fi; }

# Good inputs: images replaced, registration-only fields removed, everything else kept.
for fam in api worker migrate ops-agent; do
  out=$(run "${ARGS[@]}" -f "$FILTER" "$IN/$fam.json") || { check "$fam transforms" "jq failed"; continue; }
  res=$(printf '%s' "$out" | run -r '
    ([.containerDefinitions[] | {(.name): .image}] | add) as $img
    | if (has("taskDefinitionArn") or has("revision") or has("status") or has("requiresAttributes")
          or has("compatibilities") or has("registeredAt") or has("registeredBy")) then "registration field kept"
      elif (.family | startswith("eka-") | not) or .cpu != "256" or .networkMode != "awsvpc" then "other field changed"
      elif ([.containerDefinitions[].image | select(endswith(":old"))] | length) > 0 then "old image kept"
      elif ([.containerDefinitions[] | select(.environment[0].value != "production")] | length) > 0 then "container body changed"
      else ($img | to_entries | map("\(.key)=\(.value)") | join(" ")) end')
  case "$fam" in
    api) want="core=core.example/eka-core:abc123 edge=edge.example/eka-edge:abc123" ;;
    worker) want="worker=core.example/eka-core:abc123" ;;
    migrate) want="migrate=core.example/eka-core:abc123" ;;
    ops-agent) want="ops-agent=agent.example/eka-ops-agent:abc123" ;;
  esac
  [ "$res" = "$want" ] && check "$fam images replaced" ok || check "$fam images replaced" "got '$res'"
done

# Bad inputs must fail (non-zero exit) and write nothing usable.
for bad in bad_not_json bad_no_containers bad_unknown_containers; do
  if out=$(run "${ARGS[@]}" -f "$FILTER" "$IN/$bad.json" 2>/dev/null); then
    check "$bad rejected" "jq exited 0"
  else
    check "$bad rejected" ok
  fi
done
exit $fail
