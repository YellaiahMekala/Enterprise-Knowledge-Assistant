#!/usr/bin/env bash
# Drill: an alert the triage agent has accepted must never be lost.
# Needs Java 21, curl and Docker (for a throwaway local mail catcher). Free: no model call is made.
# Uses the built jar (cd ops-agent && mvn -B package -DskipTests) and a mailpit container on
# 127.0.0.1:11025 (SMTP) and :18025 (web/API); it does not touch the compose stack.
#
#   scripts/triage_failure_drill.sh            # all three scenarios
#   scripts/triage_failure_drill.sh model-down # or smtp-down, or restart
#
# model-down : the model endpoint refuses connections  -> a runbook-only report is still emailed
# smtp-down  : the mail server is unreachable          -> reports.failed rises, pending returns to 0
#              (this is what EkaTriageReportFailed alerts on; Alertmanager emails it by another path)
# restart    : an accepted batch is left in the journal (the process died) -> the next start emails it
set -u
cd "$(dirname "$0")/.."

# cygpath: on Windows (Git Bash) Java needs a Windows-style path; elsewhere the path is used as is
native() { cygpath -m "$1" 2>/dev/null || echo "$1"; }
JAR=$(native "$(ls ops-agent/target/eka-ops-agent-*.jar 2>/dev/null | grep -v original | head -1)")
[ -n "$JAR" ] || { echo "build the jar first: (cd ops-agent && mvn -B package -DskipTests)"; exit 2; }
PORT=18090
SMTP_PORT=11025
UI_PORT=18025
TOKEN="drill-$(date +%s)-token"
WORK=$(mktemp -d)
AGENT_PID=""
PASS=0
FAIL=0

cleanup() {
  [ -n "$AGENT_PID" ] && kill "$AGENT_PID" 2>/dev/null
  docker rm -f eka-drill-mailpit >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

check() { # description, condition result (0 = ok)
  if [ "$2" -eq 0 ]; then echo "  PASS  $1"; PASS=$((PASS + 1)); else echo "  FAIL  $1"; FAIL=$((FAIL + 1)); fi
}

metric() { curl -s "http://127.0.0.1:$PORT/actuator/prometheus" | grep "^$1" | awk '{print int($2)}' | head -1; }

wait_for() { # seconds, command...
  local limit=$1; shift
  local i=0
  while [ $i -lt "$limit" ]; do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1; i=$((i + 1))
  done
  return 1
}

metric_is() { [ "$(metric "$1")" = "$2" ]; }
mails_is() { [ "$(mail_count)" = "$1" ]; }
mails() { curl -s "http://127.0.0.1:$UI_PORT/api/v1/messages" | grep -o '"Subject":"[^"]*"' ; }
mail_count() { curl -s "http://127.0.0.1:$UI_PORT/api/v1/messages" | grep -o '"messages_count":[0-9]*' | head -1 | cut -d: -f2; }

start_mail_catcher() {
  docker rm -f eka-drill-mailpit >/dev/null 2>&1
  docker run -d --name eka-drill-mailpit -p 127.0.0.1:$SMTP_PORT:1025 -p 127.0.0.1:$UI_PORT:8025 axllent/mailpit:v1.27 >/dev/null \
    || { echo "cannot start the mail catcher (is Docker running?)"; exit 2; }
  wait_for 30 curl -sf "http://127.0.0.1:$UI_PORT/api/v1/messages" || { echo "mail catcher did not start"; exit 2; }
}

start_agent() { # extra env assignments...
  env OPS_AGENT_PORT=$PORT OPS_AGENT_WEBHOOK_TOKEN="$TOKEN" OPS_AGENT_RUNBOOK_FILE="$(native "$PWD/docs/runbooks.md")" \
      EKA_ALERT_EMAIL_TO=oncall@example.test EKA_ALERT_EMAIL_FROM=eka@example.test EKA_ALERT_SMTP_AUTH=false \
      EKA_ALERT_SMTP_HOST=127.0.0.1 EKA_ALERT_SMTP_PORT=$SMTP_PORT \
      OPS_AGENT_PROMETHEUS_URL=http://127.0.0.1:1 OPS_AGENT_CORE_URL=http://127.0.0.1:1 OPS_AGENT_EDGE_MANAGEMENT_URL=http://127.0.0.1:1 \
      "$@" java -jar "$JAR" >"$WORK/agent.log" 2>&1 &
  AGENT_PID=$!
  # health goes DOWN when the mail server is down, so wait on the metrics endpoint
  wait_for 60 curl -sf "http://127.0.0.1:$PORT/actuator/prometheus" || { echo "agent did not start"; tail -20 "$WORK/agent.log"; exit 2; }
}

stop_agent() { kill "$AGENT_PID" 2>/dev/null; wait "$AGENT_PID" 2>/dev/null; AGENT_PID=""; }

ALERT='{"version":"4","status":"firing","receiver":"ops-agent","groupKey":"drill","alerts":[{"status":"firing","labels":{"alertname":"EkaTargetDown","severity":"page","job":"core"},"annotations":{"summary":"Prometheus cannot scrape core"},"startsAt":"2026-11-08T10:00:00Z"}]}'

post_alert() { curl -s -o /dev/null -w "%{http_code}" -X POST "http://127.0.0.1:$PORT/alerts" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "$ALERT"; }

scenario_model_down() {
  echo "== model-down: the model endpoint refuses connections"
  start_mail_catcher
  start_agent EKA_CHAT_API_KEY=drill-not-a-key EKA_CHAT_BASE_URL=http://127.0.0.1:1/v1
  code=$(post_alert)
  check "the webhook answered 202" $([ "$code" = "202" ]; echo $?)
  wait_for 60 mails_is 1
  check "a report was emailed anyway" $([ "$(mail_count)" = "1" ]; echo $?)
  mails | sed 's/^/        /'
  check "it says it is runbook-only because the model call failed" \
    $(curl -s "http://127.0.0.1:$UI_PORT/api/v1/messages" | grep -q 'EkaTargetDown'; echo $?)
  check "reports.sent = 1 and fallback = 1 and failed = 0" \
    $([ "$(metric eka_ops_reports_sent_total)" = 1 ] && [ "$(metric eka_ops_reports_fallback_total)" = 1 ] && [ "$(metric eka_ops_reports_failed_total)" = 0 ]; echo $?)
  check "pending is back to 0" $(wait_for 60 metric_is eka_ops_reports_pending 0; echo $?)
  stop_agent
}

scenario_smtp_down() {
  echo "== smtp-down: the mail server is unreachable (3 tries for the report and 3 for the notice, 5 s and 10 s apart: about 30 s)"
  start_agent EKA_ALERT_SMTP_PORT=1
  code=$(post_alert)
  check "the webhook answered 202" $([ "$code" = "202" ]; echo $?)
  check "pending is 1 while it retries" $(wait_for 10 metric_is eka_ops_reports_pending 1; echo $?)
  check "the batch ends failed (counted for EkaTriageReportFailed)" \
    $(wait_for 90 metric_is eka_ops_reports_failed_total 1; echo $?)
  check "pending is back to 0" $(wait_for 60 metric_is eka_ops_reports_pending 0; echo $?)
  check "sent = 0" $([ "$(metric eka_ops_reports_sent_total)" = 0 ]; echo $?)
  check "the log says the failure alert will fire" $(grep -q 'EkaTriageReportFailed will fire' "$WORK/agent.log"; echo $?)
  stop_agent
}

scenario_restart() {
  echo "== restart: a batch was accepted, then the process died before the report"
  start_mail_catcher
  mkdir -p "$WORK/journal"
  echo "[$(echo "$ALERT" | sed 's/.*"alerts":\[\(.*\)\]}$/\1/')]" >"$WORK/journal/11111111-aaaa-bbbb-cccc-222222222222.json"
  start_agent OPS_AGENT_JOURNAL_DIR="$(native "$WORK/journal")"
  check "the interrupted batch was emailed after the restart" $(wait_for 60 mails_is 1; echo $?)
  mails | sed 's/^/        /'
  check "alerts.recovered = 1" $([ "$(metric eka_ops_alerts_recovered_total)" = 1 ]; echo $?)
  check "the journal is empty again" $([ -z "$(ls "$WORK/journal" 2>/dev/null)" ]; echo $?)
  stop_agent
}

which_one=${1:-all}
case "$which_one" in
  model-down) scenario_model_down ;;
  smtp-down) scenario_smtp_down ;;
  restart) scenario_restart ;;
  all) scenario_model_down; scenario_smtp_down; scenario_restart ;;
  *) echo "usage: $0 [model-down|smtp-down|restart]"; exit 2 ;;
esac

echo
echo "drill: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
