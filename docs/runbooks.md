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
