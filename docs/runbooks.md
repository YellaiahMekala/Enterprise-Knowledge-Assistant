# Runbooks

Each alert in `monitoring/alerts.yml` links to its section here. Commands assume the Compose stack from the repository root; replace `docker compose` with your platform's equivalent elsewhere.

## SLOs

| SLO | Target | Measured from |
|---|---|---|
| Availability | 99.5% of core requests do not end in 5xx (30 days) | `eka_http_requests_total` |
| Search latency | 95% of `POST /api/v1/search` within 1 s | `eka_http_request_duration_seconds` |

Error budget: 0.5% of requests, about 3.6 hours of full outage in 30 days. `EkaHighErrorRate` fires at 14.4× that rate, which spends 2% of the monthly budget in an hour.

Alert severities: `page` needs someone now, `ticket` can wait for working hours.

## First checks for any alert

```bash
docker compose ps                                     # what is running and healthy
curl -s localhost:8000/health/ready                   # core and database
docker compose logs --since 15m api worker edge | grep -iE "error|warn" | tail -50
```
Every error response carries a `request_id`. Search the logs for it to follow one request across the edge and the core.

On AWS the same lines are in CloudWatch Logs (log group from `terraform output log_group`, streams `eka/<container>/<task id>`); the triage agent searches them when `OPS_AGENT_CLOUDWATCH_LOG_GROUP` is set.

With the monitoring profile, the same lines are in Loki for 3 days: Grafana, Explore, data source Loki, query `{service="core-behind-edge"} |= "ERROR"` (services are labelled by their Compose name: `api`, `worker`, `core-behind-edge`, `edge`, `db`, ...). The triage agent runs the same kind of search with its `searchLogs` tool and puts what it found in the alert email.

## EkaHighErrorRate

**Meaning:** more than 7.2% of core requests returned 5xx for 5 minutes.

1. Find which routes fail. In Prometheus: `sum by (route, status) (rate(eka_http_requests_total{status=~"5.."}[5m]))`.
2. All routes failing usually means the database. Check `/health/ready` and `docker compose logs db`.
3. Only `/api/v1/chat` failing usually means the chat model provider (timeouts, 429, an expired key). The core logs the provider error with the request id. Fall back with `EKA_CHAT_PROVIDER=fake` only for a demo, never silently in production.
4. Errors that started right after a deploy: roll back to the previous image tag.

**Resolved when:** the ratio stays under 0.5% for 15 minutes.

## EkaSearchSlow

**Meaning:** search p95 has been above 1 s for 10 minutes.

1. Check the load: `sum(rate(eka_http_requests_total{route="/api/v1/search"}[5m]))`.
2. Check the database: CPU, and slow queries in `pg_stat_activity`.
3. An owner above `EKA_EXACT_SEARCH_MAX_CHUNKS` (20,000) uses HNSW. If one very large owner is slow, lower `EKA_HNSW_EF_SEARCH` (400). Spike S-2 measured recall@10 of 0.85–0.96 at 200, so check the evaluation still passes before keeping it.
4. Embedding runs on CPU in the api container. Sustained CPU saturation there means scale out the api.

## EkaTargetDown

**Meaning:** Prometheus has not scraped `core` or `edge` for 2 minutes.

1. Check whether the service is up (`docker compose ps`), and restart it if it exited. Read its last logs first.
2. Core up but the scrape fails: the admin key file `monitoring/secrets/admin_key` is missing or wrong. A scrape with a bad key fails with 401 and the target shows it.
3. Edge up but the scrape fails: the management port 8081 is not reachable from Prometheus.

## EkaEdgeCircuitOpen

**Meaning:** the edge's circuit breaker for the core is open. After at least 10 calls in a 20-call window with 50% or more failing, the edge stops calling the core and answers `503 circuit-open` straight away. After 30 s it lets 3 test calls through and closes again if they succeed.

1. This alert is a symptom. Look for `EkaTargetDown` or `EkaHighErrorRate` on the core, and follow that runbook.
2. Core healthy but the breaker keeps opening: look for timeouts. The edge's response timeout is `spring.cloud.gateway.server.webflux.httpclient.response-timeout` (120 s by default). Slow model calls count as failures when they hit it.
3. Do not restart the edge to clear the breaker. It closes on its own once the core answers.

Tuning variables: `EKA_EDGE_CB_WINDOW`, `EKA_EDGE_CB_MIN_CALLS`, `EKA_EDGE_CB_OPEN_FOR`.

## EkaAlertDeliveryFailing

**Meaning:** Alertmanager tried to send alerts to the triage agent (`ops-agent`) and failed in the last 10 minutes. This alert does not go through the agent; it is emailed directly. Other alerts may be firing that nobody has been told about.

1. Open Alertmanager (http://localhost:9093) and read the active alerts. Follow their runbooks; there is no agent report for them.
2. Check the agent: `docker compose --profile agent ps ops-agent` and its last logs. Restart it if it exited.
3. Agent up but deliveries still fail: Alertmanager's log shows the HTTP status. 401 means the token in `monitoring/secrets/webhook_token` differs from `OPS_AGENT_WEBHOOK_TOKEN`.
4. The alert resolves on its own 10 minutes after the last failed delivery.

**On AWS** the same alarm means a CloudWatch alarm has waited 15 minutes in the SQS queue `<name>-alarms`: the agent is not polling. Open the ECS service `<name>-ops-agent` and its log stream `eka/ops-agent/...`; check that the task role may read the queue. Open the CloudWatch alarms page for what is firing.

## EkaAlertDeliveryDeadLetters

**Meaning (AWS only):** alarm messages failed five times and SQS moved them to `<name>-alarms-dead`. Emailed directly, not through the agent.

1. Read the messages in the dead-letter queue (SQS console, "Send and receive messages", poll). Each is a CloudWatch alarm notification; follow the runbook section of its `AlarmName`.
2. Look in the agent's log stream for the error at the same time. The agent deletes messages it cannot parse, so a dead letter usually means the agent crashed while handling it.
3. After the cause is fixed, purge the dead-letter queue; the alarm resolves when it is empty.

## EkaLlmFailoverBurst

**Meaning:** a chat model failed (unavailable, or a timeout) before any text more than 5 times in 5 minutes, and the core moved those questions to the next model in `EKA_CHAT_FALLBACKS` (ADR-038). Users still get answers, from the fallback model, so this is a ticket, not a page.

1. Which model, and why: `sum by (from_model, reason) (increase(eka_llm_failover_total[15m]))`. `breaker_open` means the primary is being skipped without a call; `unavailable` or `timeout` means it is being called and failing.
2. Breaker state: `eka_llm_breaker_state` (0 closed, 1 half-open, 2 open). Open lasts 30 s, then 3 test calls decide.
3. Check the provider's status page and the core log: `docker compose logs --since 15m api | grep "chat model"`. A `401` or `403` means the key is wrong or revoked; rotate it and restart the core.
4. Watch cost: the fallback model may be priced differently (`eka:llm_cost_usd:increase1h`).
5. If every model fails, users get `502 model-unavailable` or `504 model-timeout` and `EkaHighErrorRate` fires as well.

## High token spend

**Meaning:** tokens or cost are higher than usual. There is no alert for this, because a normal level depends on the deployment; check it on the Grafana panels "Model tokens per minute" and "Model cost per hour".

1. Which model: `eka:llm_tokens:rate5m` and `eka:llm_cost_usd:increase1h` by model.
2. Which users or days (admin only): `GET /api/v1/admin/usage?group_by=user` or `group_by=day`, with `from` and `to` (at most 92 days). The report has counts and timings only, never question text.
3. A failover to a more expensive model raises cost per answer; see EkaLlmFailoverBurst.
4. Limits: per-user rate limits at the edge, `EKA_MAX_OUTPUT_TOKENS` and `EKA_MAX_CONTEXT_CHARS` bound each answer. Cost appears only when `EKA_CHAT_PRICE_INPUT_PER_1M` and `EKA_CHAT_PRICE_OUTPUT_PER_1M` are set; with the offline model, token counts are estimates.

## EkaTriageReportFailed

Also see **EkaTriageReportStuck** below.

**Meaning:** the triage agent accepted an alert (it answered Alertmanager with 202) but its report did not go out. `EkaTriageReportFailed`: the email failed 3 times, 5 s and 10 s apart. `EkaTriageReportStuck`: an accepted alert has had no report for 15 minutes, so the investigation is hanging. Alertmanager sends these two alerts by email itself, not through the agent. The original alert is still active in Alertmanager.

1. Read the original alert in Alertmanager (http://localhost:9093) and work it from this runbook directly; do not wait for the agent.
2. Mail problem: `docker compose logs --since 30m ops-agent | grep "sending the report failed"` shows the exception class. Check `EKA_ALERT_SMTP_HOST`, `EKA_ALERT_SMTP_PORT` and the credentials; a `MailAuthenticationException` means a wrong or revoked password.
3. Stuck: `docker compose logs --since 30m ops-agent` for a model call that never returned. Restart the agent (`docker compose --profile agent restart ops-agent`); pending work is lost, which is why the original alert stays in Alertmanager.
4. Counts: `eka_ops_alerts_accepted_total`, `eka_ops_reports_sent_total`, `eka_ops_reports_failed_total` and `eka_ops_reports_pending` (Prometheus, job `ops-agent`).

## EkaTriageReportStuck

The triage agent accepted an alert (202) and has been working on it longer than the stuck threshold, so no report or notice has gone out. Same family as `EkaTriageReportFailed`; the report is late, not known to have failed.

1. Work the original alert from this runbook directly; do not wait for the agent.
2. `docker compose logs --since 30m ops-agent` for a model call that never returned or a slow Prometheus or log query.
3. Restart the agent (`docker compose --profile agent restart ops-agent`); pending work is lost, which is why step 1 comes first.
4. Check `eka_ops_reports_pending` (Prometheus, job `ops-agent`); it should fall back to 0.

## Backup and restore

```bash
scripts/db_backup.sh                         # backups/eka-<UTC stamp>.dump and .roles.sql
scripts/db_restore.sh backups/eka-<stamp>.dump eka_copy    # restore into a new database
scripts/restore_drill.sh                     # backup, restore to scratch, compare, drop
```
- The roles file holds role definitions without passwords. After restoring into a new cluster, set the passwords again from your secret store.
- To restore over the live database, stop `api` and `worker` first, run `scripts/db_restore.sh <dump> eka`, then start them and check `/health/ready`.
- `backups/` is git-ignored. Copy dumps off the host: a backup on the same disk as the database is not a backup.
- Uploaded files live in the `storage` volume, separately from the database. Back that volume up at the same time, or restored documents will point to missing files.

**Drill result, 2026-11-07, local:** passed in 8 s. Migration version, row counts (documents, chunks, vectors, conversations, messages) and the 5 tables with forced row-level security matched.

## Web fallback gives no answer (optional feature, ADR-030)

Not an alert; for when `EKA_WEB_FALLBACK_ENABLED=true` and weak-evidence questions are still refused.

1. Search the API log (Grafana, Loki): `{service="api"} |= "web f"`. `web fallback fetched=1 ready=1` means the page was stored and indexed; the refusal then came from the page itself (weak match, or the model declined).
2. `web fetch refused host=... reason=...` gives a fixed reason: `host_not_allowed` (a redirect left the allowlist; add the target host only if it is official), `private_address` (the name resolves to a private or loopback address; do not allow it), `not_https`, `too_large` (raise `EKA_WEB_MAX_PAGE_KB` with care), `content_type`, `timeout`, `dns`, `network`, `http_<status>`.
3. `ready=0` with `web pages still being processed`: the worker did not finish within `EKA_WEB_INGEST_WAIT_SECONDS`. The page is used from the next question on; check the worker log and the document's status.
4. A page is fetched again only after `EKA_WEB_REFRESH_HOURS`. To force a refresh, delete the user's copy (it is listed among their documents with its source URL).
