# ADR-040: Ship local container logs to CloudWatch Logs with Vector

| | |
|---|---|
| Status | Accepted (task P16-B, built 2026-11-13) |
| Date | 2026-11-13 |
| Decision owner | Maintainer |
| Review trigger | Alloy gains a CloudWatch Logs writer; the stack runs on AWS (ECS's awslogs driver then ships the logs and this service is not used); log volume where the CloudWatch ingestion price matters. |
| Related | ADR-033, ADR-034, ADR-035, FR-49 |

## Context
The triage agent's log tool has two stores (ADR-035): Loki for the local stack and CloudWatch Logs for AWS. On AWS the ECS `awslogs` driver writes streams named `eka/<container>/<task id>` (`infra/aws/ecs.tf`). Locally nothing wrote to CloudWatch, so the CloudWatch adapter had only been tried against log events put there by its own tests, never against real container output. The plan was to add a CloudWatch writer to the existing Alloy collector.

Alloy v1.10.2 has no CloudWatch Logs writer. Validating a config with `otelcol.exporter.awscloudwatchlogs` fails with "cannot find the definition of component name". Alloy's OpenTelemetry Collector build does not include that exporter.

## Decision
1. **A second collector, Vector 0.51.1,** in a `log-shipper` compose service under the `cloudwatch` profile, so it only runs when asked for. Alloy keeps shipping to Loki unchanged.
2. **Source:** the Docker socket (read only), only containers with this compose project's label, without the shipper itself and LocalStack (their output would be read back).
3. **Stream names match AWS.** A remap step maps the compose service to the ECS container name (`api` and `core-behind-edge` become `core`) and keeps the first 12 characters of the container id. Streams are `eka/<container>/<id12>` in the group `CLOUDWATCH_LOG_GROUP` (default `/eka-local`), so `CloudWatchLogStore`'s prefix search works the same way locally and on AWS.
4. **Empty lines are dropped** in the remap step: Vector's CloudWatch sink panics on a zero-length message ("payload should never be zero length"). The service also has `restart: unless-stopped`.
5. **LocalStack 4.9 by default.** `CLOUDWATCH_ENDPOINT_URL` defaults to `http://localstack:4566` with the dummy credentials `test`. Pointing at real AWS needs the endpoint set empty and real `CLOUDWATCH_ACCESS_KEY_ID` and `CLOUDWATCH_SECRET_ACCESS_KEY`; that costs money and is not done without the owner's approval.
6. **CI** validates the Vector config (`vector validate --no-environment`) in the monitoring job.

## Flow
```
containers (compose project label) -> Docker socket -> Vector docker_logs
  -> remap: drop empty lines, service -> container name, id -> 12 chars
  -> aws_cloudwatch_logs  group /eka-local, stream eka/<container>/<id12>  (LocalStack or AWS)
ops agent: OPS_AGENT_CLOUDWATCH_LOG_GROUP=/eka-local -> CloudWatchLogStore -> FilterLogEvents
```

## Options considered
| Option | Assessment |
|---|---|
| Vector next to Alloy (chosen) | Has a maintained CloudWatch Logs sink and a Docker source; one small extra container under a profile |
| Alloy with `otelcol.exporter.awscloudwatchlogs` | Not in Alloy v1.10.2 (checked) |
| Docker `awslogs` logging driver | What ECS uses, but it is set per container and would change every service's logging, including Loki's input |
| Fluent Bit | Also has a CloudWatch output; Vector's remap language made the name mapping a few lines |
| A script that copies from Loki to CloudWatch | Another moving part with its own failure modes |

## Consequences
- Two collectors read the Docker socket when the profile is on. The shipper is limited to 128 MB of memory.
- The stream id is the container id, not the ECS task id; the agent searches by the `eka/<container>/` prefix, so it does not matter.
- Tested: logs from the core were shipped to LocalStack (stream `eka/core/<id12>` created), and `ShippedLogsLiveTest` (2 tests, enabled with `EKA_LIVE_SHIPPED_LOG_GROUP`) searched them through the agent's `LogSearch` with and without an `ERROR` filter. Not run against real AWS CloudWatch.
