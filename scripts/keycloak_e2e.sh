#!/usr/bin/env bash
# Logs in to the Keycloak test realm and calls the core through the edge (stack: profiles edge + idp).
# Needs EKA_KEYCLOAK_ALICE_PASSWORD and EKA_KEYCLOAK_BOSS_PASSWORD in the environment or .env.
set -euo pipefail
[ -f .env ] && set -a && . ./.env && set +a
kc=http://localhost:8180/realms/eka/protocol/openid-connect/token
edge=http://localhost:8080

token() {
  curl -sf -d client_id=eka-ui -d grant_type=password -d username="$1" --data-urlencode password="$2" "$kc" |
    python -c "import sys,json;print(json.load(sys.stdin)['access_token'])"
}
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
fail=0
check() { # name expected actual
  if [ "$2" = "$3" ]; then echo "PASS  $1 ($3)"; else echo "FAIL  $1: expected $2, got $3"; fail=1; fi
}

alice=$(token alice "$EKA_KEYCLOAK_ALICE_PASSWORD")
boss=$(token boss "$EKA_KEYCLOAK_BOSS_PASSWORD")

check "no token"                    401 "$(code $edge/api/v1/me)"
check "garbage token"               401 "$(code -H 'Authorization: Bearer abc.def.ghi' $edge/api/v1/me)"
check "alice: /me"                  200 "$(code -H "Authorization: Bearer $alice" $edge/api/v1/me)"
check "alice: documents"            200 "$(code -H "Authorization: Bearer $alice" $edge/api/v1/documents)"
check "alice: admin status denied"  403 "$(code -H "Authorization: Bearer $alice" $edge/api/v1/admin/status)"
check "boss: admin status"          200 "$(code -H "Authorization: Bearer $boss" $edge/api/v1/admin/status)"
role=$(curl -s -H "Authorization: Bearer $boss" $edge/api/v1/me | python -c "import sys,json;print(json.load(sys.stdin)['role'])")
check "boss role claim mapped"      admin "$role"
exit $fail
