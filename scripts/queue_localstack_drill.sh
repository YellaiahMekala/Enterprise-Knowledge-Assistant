#!/usr/bin/env bash
# PQ1.2.5: CloudWatch alarm -> SNS -> SQS -> ops-agent -> triage (scripted model) -> email, all local.
# No AWS account and no paid call: LocalStack (dummy credentials), a scripted model (fake_openai.py),
# Mailpit as the mail server. Needs Docker, JDK 21 and the built jar (cd ops-agent && mvn -DskipTests package).
# Containers it starts are named pq125-*; it stops only those. Set KEEP=1 to leave them running.
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
LS_PORT=4567; MAIL_UI=8125; MAIL_SMTP=1125; MODEL_PORT=8099; AGENT_PORT=8195
Q_URL="http://localhost:$LS_PORT/000000000000/eka-alarms"
DLQ_URL="http://localhost:$LS_PORT/000000000000/eka-alarms-dead"
export MSYS_NO_PATHCONV=1
fail=0
ok()   { echo "PASS $1"; }
bad()  { echo "FAIL $1"; fail=1; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
aws_() { docker exec pq125-localstack awslocal --region eu-west-1 "$@"; }
attr() { aws_ sqs get-queue-attributes --queue-url "$1" --attribute-names All --query "Attributes.$2" --output text; }
mails() { curl -s "http://localhost:$MAIL_UI/api/v1/messages" | python -c "import sys,json; d=json.load(sys.stdin); print(d['total'])"; }
# Native Windows python/java do not understand /d/... paths (Git Bash); convert when cygpath exists.
wp() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf %s "$1"; fi; }
wait_for() { for _ in $(seq 1 "$2"); do eval "$1" && return 0; sleep 1; done; return 1; }

cleanup() {
  [ -n "${AGENT_PID:-}" ] && kill "$AGENT_PID" 2>/dev/null
  [ -n "${MODEL_PID:-}" ] && kill "$MODEL_PID" 2>/dev/null
  if [ "${KEEP:-0}" != 1 ]; then
    for c in ${STARTED:-}; do docker rm -f "$c" >/dev/null 2>&1; done
  fi
}
trap cleanup EXIT

STARTED=""
# Remove leftovers of an earlier interrupted run (stopped pq125-* containers) so the names are free.
for c in pq125-localstack pq125-mailpit; do
  docker ps -a --filter "name=^$c\$" --filter status=exited --format x | grep -q . && docker rm -f "$c" >/dev/null 2>&1
done
if ! docker ps --format '{{.Names}}' | grep -qx pq125-localstack; then
  docker run -d --name pq125-localstack -e SERVICES=logs,sqs,sns,cloudwatch -p 127.0.0.1:$LS_PORT:4566 localstack/localstack:4.9 >/dev/null && STARTED="$STARTED pq125-localstack"
fi
if ! docker ps --format '{{.Names}}' | grep -qx pq125-mailpit; then
  docker run -d --name pq125-mailpit -p 127.0.0.1:$MAIL_UI:8025 -p 127.0.0.1:$MAIL_SMTP:1025 axllent/mailpit:v1.27 >/dev/null && STARTED="$STARTED pq125-mailpit"
fi
wait_for "curl -sf http://localhost:$LS_PORT/_localstack/health >/dev/null" 90 || { echo "localstack not up"; exit 1; }

echo "== 1. Terraform: apply the queue wiring from infra/aws/alarms.tf to LocalStack"
tf="$root/infra/aws/localstack/run_tf.sh"
"$tf" init -no-color >/dev/null 2>&1
"$tf" apply -auto-approve -no-color 2>&1 | grep -E "^Apply complete|Error"
check "queue eka-alarms exists" "aws_ sqs get-queue-url --queue-name eka-alarms >/dev/null"
check "redrive policy: 5 receives, then eka-alarms-dead" "attr $Q_URL RedrivePolicy | grep -q '\"maxReceiveCount\":5' && attr $Q_URL RedrivePolicy | grep -q eka-alarms-dead"
check "SNS topic has an sqs subscription to the queue" "aws_ sns list-subscriptions --query 'Subscriptions[].Protocol' --output text | grep -q sqs"

echo "== 2. Dead-letter path: a message received 5 times without delete moves to the DLQ"
aws_ sqs send-message --queue-url "$Q_URL" --message-body '{"probe":"never-deleted"}' >/dev/null
aws_ sqs set-queue-attributes --queue-url "$Q_URL" --attributes VisibilityTimeout=0 >/dev/null
for _ in 1 2 3 4 5 6; do aws_ sqs receive-message --queue-url "$Q_URL" --wait-time-seconds 1 >/dev/null; done
check "message is in eka-alarms-dead" "wait_for '[ \"\$(attr $DLQ_URL ApproximateNumberOfMessages)\" = 1 ]' 20"
aws_ sqs purge-queue --queue-url "$DLQ_URL" >/dev/null
aws_ sqs set-queue-attributes --queue-url "$Q_URL" --attributes VisibilityTimeout=60 >/dev/null

echo "== 3. Start the scripted model and the ops-agent (real jar) polling the queue"
python "$(wp "$root/scripts/fake_openai.py")" $MODEL_PORT 2>"${TMPDIR:-/tmp}/pq125_model.log" &
MODEL_PID=$!
curl -s -X DELETE "http://localhost:$MAIL_UI/api/v1/messages" >/dev/null
jar="$(ls "$root"/ops-agent/target/eka-ops-agent-*.jar | head -1)"
jar="$(wp "$jar")"; runbook="$(wp "$root/docs/runbooks.md")"
agent_log="${TMPDIR:-/tmp}/pq125_agent.log"
OPS_AGENT_PORT=$AGENT_PORT OPS_AGENT_WEBHOOK_TOKEN=drill-dummy-token OPS_AGENT_ALARM_QUEUE_URL="$Q_URL" OPS_AGENT_CLOUDWATCH_ENDPOINT_URL="http://localhost:$LS_PORT" \
AWS_REGION=eu-west-1 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
EKA_CHAT_API_KEY=dummy EKA_CHAT_BASE_URL="http://localhost:$MODEL_PORT/v1" EKA_CHAT_MODEL=scripted \
OPS_AGENT_RUNBOOK_FILE="$runbook" \
EKA_ALERT_EMAIL_TO=oncall@example.test EKA_ALERT_EMAIL_FROM=eka-agent@example.test \
EKA_ALERT_SMTP_HOST=localhost EKA_ALERT_SMTP_PORT=$MAIL_SMTP EKA_ALERT_SMTP_AUTH=false \
  "${JAVA_HOME:+$JAVA_HOME/bin/}java" -jar "$jar" >"$agent_log" 2>&1 &
AGENT_PID=$!
check "agent started and is polling" "wait_for 'grep -q \"polling .* for CloudWatch alarms\" $agent_log' 90"

echo "== 4. A real CloudWatch alarm fires: set-alarm-state ALARM on EkaHighErrorRate (alarm action -> SNS -> SQS)"
aws_ cloudwatch set-alarm-state --alarm-name EkaHighErrorRate --state-value ALARM \
  --state-reason "Threshold Crossed: 1 datapoint [0.31] was greater than 0.072" >/dev/null
check "one report email arrives in Mailpit" "wait_for '[ \"\$(mails)\" -ge 1 ]' 60"
curl -s "http://localhost:$MAIL_UI/api/v1/messages" | python -c "
import sys, json
m = json.load(sys.stdin)['messages'][0]
print('  subject:', m['Subject']); print('  to:', [t['Address'] for t in m['To']])"
mid=$(curl -s "http://localhost:$MAIL_UI/api/v1/messages" | python -c "import sys,json; print(json.load(sys.stdin)['messages'][0]['ID'])")
curl -s "http://localhost:$MAIL_UI/api/v1/message/$mid" | python -c "import sys,json; print(json.load(sys.stdin)['Text'])" | sed 's/^/  | /' | head -30
check "report quotes the scripted model's runbook evidence" "curl -s http://localhost:$MAIL_UI/api/v1/message/$mid | grep -q 'runbook:'"
check "queue is empty after success (message deleted)" "wait_for '[ \"\$(attr $Q_URL ApproximateNumberOfMessages)\" = 0 ] && [ \"\$(attr $Q_URL ApproximateNumberOfMessagesNotVisible)\" = 0 ]' 20"

echo "== 5. Recovery (OK) and a malformed message: no email, both deleted"
before=$(mails)
aws_ cloudwatch set-alarm-state --alarm-name EkaHighErrorRate --state-value OK --state-reason "recovered" >/dev/null
aws_ sqs send-message --queue-url "$Q_URL" --message-body 'this is not a CloudWatch alarm' >/dev/null
check "malformed message logged as dropped" "wait_for 'grep -q \"dropped a queue message that is not a CloudWatch alarm\" $agent_log' 30"
sleep 3
check "no extra email for OK state or garbage" "[ \"\$(mails)\" = \"$before\" ]"
check "queue empty again" "wait_for '[ \"\$(attr $Q_URL ApproximateNumberOfMessages)\" = 0 ]' 20"
check "dead-letter queue empty" "[ \"\$(attr $DLQ_URL ApproximateNumberOfMessages)\" = 0 ]"

echo "== agent log (alarm lines)"
grep -E "polling|triage report sent|dropped" "$agent_log" | sed 's/^/  /'
echo "== 6. Terraform destroy"
"$tf" destroy -auto-approve -no-color 2>&1 | grep -E "^Destroy complete|Error"
[ $fail = 0 ] && echo "ALL PASSED" || echo "SOME FAILED"
exit $fail
