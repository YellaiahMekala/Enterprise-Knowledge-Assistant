# ADR-035: Log search for the triage agent with Loki and Alloy

| | |
|---|---|
| Status | Accepted (built; tested with a scripted model and against a real Loki; not run with a live model) |
| Date | 2026-11-11 |
| Decision owner | Maintainer |
| Review trigger | A deployment outside Docker Compose (on AWS the logs go to CloudWatch), a log line that leaks a credential the masking misses, or log volume above what a single Loki process keeps for 3 days. |
| Related | ADR-027, ADR-028, ADR-033 |

## Context
The triage agent (ADR-033) could read metrics, health and runbooks, but not logs. Metrics say that requests fail; the error lines say why. ADR-033 recorded that a log tool would need a log store, which the project did not have.

## Decision
1. **Loki as the log store, Alloy as the collector,** both in the `monitoring` Compose profile. Alloy discovers this project's containers through the Docker socket and labels every line with its Compose service (`service="api"`, `"worker"`, `"core-behind-edge"`, ...). Loki keeps 3 days. Grafana gets Loki as a second data source.
2. **A read-only tool, `searchLogs(service, text, minutes)`.** The model never writes LogQL. It picks a service from a fixed list, a plain text to look for and a window of 1 to 60 minutes, and the tool builds `{service="..."} |= "..."` itself. The text may hold only letters, digits, spaces and a few punctuation marks (no quotes, backslashes or backticks), so it cannot end the string it goes into; at most 100 characters.
3. **Small, masked results.** At most 20 newest lines, each cut to 300 characters. Values that follow `api key`, `x-api-key`, `authorization`, `password`, `secret` or `token` are replaced by `***` before the model or the report sees them.
4. **Same rules as the other tools:** a GET to a base URL fixed at start-up, counted in the 5-call budget, logged on `eka.ops.audit`. Without `OPS_AGENT_LOKI_URL` the tool answers that log search is not configured.

## Options considered
| Option | Assessment |
|---|---|
| Loki with Alloy (chosen) | Indexes labels only, so it is small enough for a laptop; LogQL over HTTP fits the read-only GET tool; Grafana already runs. |
| Loki with Promtail | Promtail is deprecated in favour of Alloy. |
| Elasticsearch or OpenSearch | Full-text index and more query power, but far more memory and operations than this project needs. |
| The agent reads `docker logs` through the Docker API | Gives the agent control of Docker, which breaks the read-only rule of ADR-033. Rejected. |
| CloudWatch Logs | The right store on AWS (ADR-034), but not available locally. A CloudWatch tool would be a second adapter behind the same tool. |

## Consequences
- Alloy mounts the Docker socket, which gives it full control of Docker on that machine (`:ro` does not limit the API). Acceptable for a local stack only.
- Masking is pattern-based. It catches the common `name=value` and `name: value` shapes, not every secret format. It is a safety net, not a guarantee that logs are clean; the core already avoids logging secrets.
- Lines are found by exact, case-sensitive text. That keeps queries cheap and predictable, but a model that guesses the wrong word finds nothing; the tool says so plainly.
- Checked: 9 tests against a stub Loki (query built in code, newest-first merge across streams, masking, refusals that never reach Loki, errors as text, cut lines), 2 against a real Loki fed by Alloy, and an agent-loop test where a scripted model calls `searchLogs`. Not checked: whether a live model searches well.

**Update 2026-11-12 (CloudWatch Logs adapter built).** The search rules (fixed service list, plain text, 1 to 60 minutes, masking, 20 lines of 300 characters) now sit in `LogSearch`, and the store behind them is a `LogStore` port with two adapters: `LokiLogStore` (unchanged behaviour) and `CloudWatchLogStore`. Setting `OPS_AGENT_CLOUDWATCH_LOG_GROUP` selects CloudWatch; otherwise `OPS_AGENT_LOKI_URL` selects Loki. The adapter maps the service name to the Terraform stream prefix `eka/<container>/` (api and core-behind-edge to `core`; db, prometheus and alertmanager have no stream and the tool says so), sends the checked text as one quoted filter term, pages up to 5 pages of 10,000 events because `FilterLogEvents` returns oldest first, and keeps the newest lines. It also checks the text itself, so a server that ignores filter patterns cannot widen the result. AWS errors come back as one short line. The task role gets `logs:FilterLogEvents` and `logs:DescribeLogStreams` on this log group only (`infra/aws/iam.tf`). Checked: 8 tests against a stub client and 3 against LocalStack 3.8 (the newest LocalStack images need a licence token). That run found that LocalStack ignores filter patterns, which is why the adapter filters too. Not run against real AWS, and the agent itself is not deployed on AWS by the Terraform.
