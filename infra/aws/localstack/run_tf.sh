#!/usr/bin/env bash
# Applies the alarm queue wiring from ../alarms.tf to LocalStack (no AWS account, dummy credentials).
# Usage: run_tf.sh <terraform args>, e.g.  run_tf.sh init   run_tf.sh apply -auto-approve   run_tf.sh destroy -auto-approve
# Needs Docker and a LocalStack on the host at port ${LS_PORT:-4567}:  docker run -d -p 127.0.0.1:4567:4566 localstack/localstack:4.9
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
work="${TF_WORK:-$here/.work}"
mkdir -p "$work"
cp "$here/harness.tf" "$work/harness.tf"
# From the SNS topic to the end of the topic subscription: the real queue path, unchanged.
awk '/^resource "aws_sns_topic" "alarms"/{p=1} p{print} /^resource "aws_sns_topic_subscription" "alarms_to_queue"/{s=1} s&&/^}/{exit}' \
  "$here/../alarms.tf" > "$work/alarms_queue_path.tf"
MSYS_NO_PATHCONV=1 docker run --rm -v "$work:/w" -w /w \
  -e TF_VAR_endpoint="http://host.docker.internal:${LS_PORT:-4567}" \
  hashicorp/terraform:1.17.2 "$@"
