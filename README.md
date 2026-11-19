# Enterprise Knowledge Assistant (EKA)

[![CI](https://github.com/YellaiahMekala/Enterprise-Knowledge-Assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/YellaiahMekala/Enterprise-Knowledge-Assistant/actions/workflows/ci.yml)

**Core stack**  
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white) ![Java 21](https://img.shields.io/badge/Java-21-ED8B00?logo=openjdk&logoColor=white) ![AI and RAG](https://img.shields.io/badge/AI-RAG-7B2CBF) ![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white) ![Spring Boot](https://img.shields.io/badge/Spring_Boot-Edge-6DB33F?logo=springboot&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white) ![pgvector](https://img.shields.io/badge/pgvector-0.8.7-4169E1) ![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white) ![pytest](https://img.shields.io/badge/pytest-testing-0A9EDC?logo=pytest&logoColor=white) ![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-CI-2088FF?logo=githubactions&logoColor=white)

Chat with your documents through a REST API. Each answer cites the document, page and passage it came from, and the service declines to answer when the retrieved evidence is weak.

> **Notice: independent demonstration project.**
> This is a generic, fictitious application built to demonstrate software engineering skills. It does not
> contain, reflect or derive from any client's or employer's data, code, functionality, architecture, designs
> or confidential information, and it is not affiliated with or endorsed by any current or former employer or
> client. All data is synthetic, and any resemblance to real people, organizations or documents is
> coincidental. Credentials in this repository are development-only. It is provided "as is", without warranty,
> and is not intended for production use without independent security review and hardening.

Architecture: Angular web UI → Spring Boot edge (Java 21: OIDC token validation, credential swap to a short-lived internal token, rate limit, audit, SSE passthrough) → FastAPI RAG core → PostgreSQL with pgvector. The core also runs on its own with API-key authentication. The sections below say what has been checked and what has not.

## Status

Everything below was run locally between 2026-11-07 and 2026-11-11 against the Docker Compose stack
(PostgreSQL 17 with pgvector, core, worker, edge, Prometheus, Alertmanager, Grafana, Loki, Alloy,
Keycloak, the triage agent) on a development laptop. All GitHub Actions jobs pass on `main`: core lint, types and
tests (Python 3.11 and 3.12), integration with the coverage gate, image build, edge, UI, API
contract, evaluation, monitoring, ops-agent and Terraform validate. The first run of the edge job
failed on a timing problem in the test fixture (a hung fake core stalled later tests); the fix is in
the history.

### Built and checked

| Area | What exists | How it was checked |
|---|---|---|
| Core API (FastAPI) | Typed settings that refuse a half-configured start, problem+json errors with a request id, liveness and readiness probes | 621 tests collected. On 2026-11-11 the whole suite ran locally, including the integration tests on a real PostgreSQL: 616 pass, 5 skipped, coverage 91.1% (gate 85%). CI runs the same suite |
| Authentication | API-key mode (SHA-256 digests, constant-time compare) and gateway mode (ES256 internal token from the edge, key set fetched from the edge) | Unit tests; a token minted by the real edge verifies in the core; behind the edge the core answers 401 to an identity-provider token, an API key and no credential |
| Isolation | Owner-scoped repositories plus row-level security that fails closed; leakage tests through search | Integration tests; two users through the edge see only their own documents |
| Ingestion | Upload (PDF, DOCX, CSV, code, text) validated by content, background worker, local BGE-small embeddings | 13 mixed files ingested through the Docker stack. On 2026-11-11 a DOCX with headings and a table, a CSV and a Java file went through it again: all ready, answers cited by section, by rows and by lines |
| Retrieval | Dense (pgvector HNSW) and full-text candidates fused by reciprocal rank; metadata filters; refusal gate on cosine similarity | Tests; evaluation below |
| Chat | Cited answers over JSON or server-sent events; verified mode (default) and fast mode; conversation memory; OpenAI-compatible adapter | Run with the fake model only: a cited answer, a `weak_evidence` refusal, both stream modes. No live model was used |
| Edge (Spring Cloud Gateway, Java 21) | OIDC token validation, credential swap to a 60-second internal token, per-user rate limit, audit log, SSE passthrough with client-disconnect cancel, problem+json for upstream failures, circuit breaker on the core route (fast 503 `circuit-open` while open), Prometheus on a private port | 47 tests in CI run 43393823859 (hung-core drill, breaker opens after repeated timeouts and its state is exported, streaming spike); through the real image: bad tokens 401, role mapping, tokens spaced about 100 ms apart, 12 of 45 rapid requests limited |
| Observability | Admin-only `/api/v1/admin/metrics`, request counts and latency by route template; Prometheus and Grafana as an opt-in Compose profile; SLO recording rules and 4 alerts as code plus a watchdog, each linked to a runbook; the watchdog (`EkaAlertDeliveryFailing`) is emailed directly when Alertmanager cannot reach the triage agent; container logs collected by Alloy into Loki (same profile), labelled by Compose service and searchable in Grafana | Prometheus scraped core and edge; the dashboard loaded in Grafana; `promtool test rules` passes 5 alert test cases; watchdog drill with the agent stopped: email in the local catcher after 70 s; Loki received the core's JSON log lines and a live test searched them |
| Operations | [Runbooks](docs/runbooks.md) per alert, SLOs with error budget, database backup and restore scripts, restore drill | Restore drill passed: migration version, row counts and row-level security identical after restore (8 s, local data) |
| Web UI (Angular) | Sign-in by API key (default build) or single sign-on through Keycloak (`--configuration sso`: authorization code with PKCE, bearer token to the edge, sign-out also ends the Keycloak session, an expired access token renewed with the refresh token before the next request); document upload and status, streamed chat with citations (web citations show the link and fetch date), conversation list | 39 unit tests (PKCE against the RFC 7636 example, state and nonce checks, one-use verifier, token exchange, refresh, one shared renewal for concurrent requests, session). API-key mode: a scripted browser run passed 10 times in a row. Single sign-on: real Chrome through Keycloak and the edge (sign-in, upload, cited answer, sign-out; signing in again asked for the password). Refresh: with the stored token marked expired, the app renewed it before the document list and before a streamed answer (both 200); a broken refresh token cleared the session and returned to the sign-in page |
| Identity provider | Keycloak realm in Compose (`--profile idp`) with two test users and an `eka-admin` role | 7 end-to-end checks through the real edge (`scripts/keycloak_e2e.sh`): no or bad token 401, user 200, admin route 403 for a user and 200 for the admin, role claim mapped. Refresh tokens rotate (single use, 30-minute idle and 8-hour session limits): a refreshed token passed the edge, reusing the old refresh token was refused, and after that attempt Keycloak refused the newer one too |
| File storage | Local disk (default) or S3 / any S3-compatible server (`EKA_STORAGE_BACKEND=s3`), chosen in one place | 9 tests against an in-process fake S3, and 2 against a real S3-compatible server in a container |
| Reranking (experiment E3) | Optional cross-encoder over the top 20 candidates, off by default ([ADR-032](docs/adr/ADR-032-optional-cross-encoder-reranking.md)); `scores.rerank` is returned when it is on | 96-question set, two chunk sizes: MRR 0.967 to 0.995 (paired interval +0.005 to +0.054) at 256 tokens, 0.946 to 0.981 at 64; but median search 16 ms to 745 ms, p95 1526 ms, so the latency rule failed and it stays off ([study](eval/reports/e3_rerank_study.md)) |
| Incident triage agent (LangChain4j, Java 21) | Receives Alertmanager webhooks, investigates with 4 read-only tools (PromQL query, service health, runbook, log search in Loki or CloudWatch Logs), emails a report; token-protected, call budget, audit log, runbook-only fallback ([ADR-033](docs/adr/ADR-033-incident-triage-agent.md), [ADR-035](docs/adr/ADR-035-log-search-loki.md)) | 80 tests in CI run 43393823859, 7 skipped (Loki and CloudWatch live ones skip unless an endpoint is set) including the full tool loop with a scripted model (2 of them need a real Loki and passed against one); drills against the real stack: a synthetic alert and a real one (core stopped, Prometheus fired `EkaTargetDown`, email in about 4 minutes) both arrived in a local mail catcher. Not run with a live model or real SMTP |
| Amazon Bedrock chat provider | `EKA_CHAT_PROVIDER=bedrock` through the Converse API, credentials from the AWS chain, no key in settings ([ADR-034](docs/adr/ADR-034-bedrock-provider-and-aws-deployment.md)). A local Converse stand-in (`python -m eka.tools.bedrock_stub`) lets the unchanged adapter and boto3 run without an account; `EKA_BEDROCK_ENDPOINT_URL` points at it and stays empty for real AWS | 10 tests against a stub client; 6 tests through real boto3 against the stand-in with fake keys (SigV4 signing, Converse JSON, the binary event stream); the 54 evaluation questions through the API with the Bedrock adapter, 54 answers recorded under the Bedrock model id. Never called Bedrock |
| Provider comparison | `python -m eka.tools.answer_run` asks the evaluation questions through the API; `python -m eka.tools.compare_runs` puts two or more runs side by side (see below) | 3 tests; first table produced (below) |
| AWS deployment (Terraform, `infra/aws`) | ECS Fargate (edge and core in one task, worker, migration task), RDS PostgreSQL 17, S3, Secrets Manager, load balancer, task role limited to the bucket and Bedrock | `terraform validate` and `fmt` pass (also in CI). Never planned or applied against an account |
| Web fallback (optional, off by default) | When the user's own documents give weak or no evidence, fetches owner-configured entry pages from an exact-host allowlist, stores each as the user's Markdown document with its URL and fetch time, lets the worker index it, then answers from those pages only; citations are typed `web` with URL and fetch date ([ADR-030](docs/adr/ADR-030-allowlisted-web-fallback.md)). The fetcher allows only https on allowlisted hosts, refuses names that resolve to private, loopback, link-local or metadata addresses, connects to the address it checked (TLS still verifies the host name), re-checks every redirect and caps size, time and content type | 63 tests (fetcher, HTML to Markdown, service, answering, settings, database columns). Live, against docs.python.org: first weak-evidence question answered from the fetched page in 14 s (47 chunks), the next question in 0.1 s from the stored copy, an off-topic question still refused; from inside the container `localhost` was refused as a private address, a redirect to a host off the list was refused, plain http was refused |
| API contract | Postman collection | 36 assertions, 0 failures against the Compose stack |

### Test evidence

Per feature (what it proves, how to run, failure modes, talking points): [docs/testing/FEATURE_TESTING_GUIDE.md](docs/testing/FEATURE_TESTING_GUIDE.md).

| Feature | Tests | How to run | Last result | CI or local |
|---|---|---|---|---|
| Core API, auth, isolation, ingestion, chat | 696 collected (79 need Docker) | `pytest -m "not integration"` | 2026-11-19: 612 passed, 5 skipped, 79 deselected; full `pytest -q` with Docker up: 691 passed, 5 skipped (edge token fixtures regenerated by `mvn test` in `gateway`) | CI and local |
| Core with real PostgreSQL | integration set | `pytest -m integration` | 2026-11-11 full suite: 616 passed, 5 skipped, coverage 91.1% (gate 85%) | CI and local |
| Lint and types | ruff, mypy strict | `ruff check .`, `ruff format --check .`, `mypy src tests` | 2026-11-19: clean, 184 files formatted, 161 files typed (`mypy src scripts`: 93 files) | CI and local |
| Retrieval evaluation | 96 questions (44 original + 52 synthetic), 24 challenge, thresholds | `python -m eka.eval --check` | 2026-11-18: gate passes locally on the 96 (Hit@3 100%, MRR 0.967); CI runs the same command | CI and local |
| Reranking study (D1.2.5) | 10 unit tests; 96 questions, 2 chunk sizes, bootstrap intervals, latency | `python -m eka.eval.rerank_study` | 2026-11-18: quality better (5 better, 0 worse at 256 tokens; 7 better, 3 worse at 64), latency over the stated limits, so rerank stays off | local only (free: local models) |
| Live answers | 44 + 10 challenge | `python -m eka.tools.answer_run` | 2026-11-13 run; all 44 hand-scored 2026-11-18: 44 correct, 10 of 10 refused | local only (paid) |
| Java edge | 47 | `cd gateway && mvn -B verify` | CI run 43393823859: green | CI and local |
| Triage agent | 92 (live ones skip) | `cd ops-agent && mvn -B verify` | 92 green (README, 2026-11-18) | CI and local |
| Triage failure drill (D1.1.6) | 3 injected failures | `scripts/triage_failure_drill.sh` | 2026-11-18: 14 of 14 checks | local only |
| Live triage agent and web fallback (PQ1.2.3) | 4 alerts; 14 fallback questions x 2 runs | `scripts/pq123_web_fallback_run.py`; alerts posted to the agent | 2026-11-18, `gpt-4o-mini`, USD 0.0076: 4 of 4 reports emailed, 19 audited tool calls, 1 of 4 reports fully correct; fallback hit rate 0 of 6 at default settings, 1 of 6 strict (4 of 6 grounded) with the gate raised to 0.72, never triggered on corpus-answerable questions; [report](eval/reports/pq1-2-3-live-triage-fallback-2026-11-18.md) | local only (paid) |
| Web UI | 39 unit, 1 browser spec | `npx ng test --watch=false`; Playwright | 39 pass; 6 local browser passes; CI browser job green (run 44296520354, 2026-11-18) | CI and local |
| API contract | 36 Postman assertions | Postman CLI as in `ci.yml` | 0 failures on the Compose stack | CI and local |
| Deploy task-definition step and alarm queue path (PQ1.2.5) | 7 jq fixture cases; 6-step LocalStack drill | `bash scripts/test_deploy_jq.sh`; `bash scripts/queue_localstack_drill.sh` | 2026-11-19: 7 of 7 jq cases; drill ALL PASSED (alarm to SNS to SQS to agent to one email, dead-letter after 5 receives, destroy clean); [report](eval/reports/pq1-2-5-localstack-2026-11-19.md); no real AWS | local only (free) |
| Admin key and digest consistency | 3 unit tests | `python -m eka.tools.sync_admin_key --check` | 2026-11-19: mismatch found in `.env` after PQ1.2.3, `--sync` fixed it, `--check` prints match | local |
| Alerts as code | 5 `promtool` cases | `promtool test rules` | pass | CI and local |
| Restore drill | 1 script | `scripts/restore_drill.sh` | counts and RLS identical, 8 s | local only |

### Load, local run (10 users for 20 s, fake chat model, 13 documents)

| Endpoint | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|
| `POST /api/v1/search` | 58 req/s | 163 ms | 231 ms | 305 ms | 0 |
| `POST /api/v1/chat` | 35 req/s | 282 ms | 358 ms | 410 ms | 0 |

These are one laptop and a fake model, so a real model's latency would dominate chat. They show the harness works and the service stays error-free under that load; they are not capacity claims.

### Measured

Retrieval on the original 44-question set over 13 short documents (one chunk each), BGE-small, 256-token chunks, run locally (the set now has 96 questions, 52 of them synthetic additions; on all 96, rerank off: Hit@1 93.8%, Hit@3 100%, MRR 0.967; see the reranking study):

| Metric | Value |
|---|---|
| Hit@1 | 95.5% |
| Hit@3 | 100% |
| MRR | 0.977 |
| Median top cosine, answerable questions | 0.710 |
| Median top cosine, unanswerable challenge questions | 0.571 |

A deliberately damaged configuration (16-token chunks, 117 chunks) fails the gate: Hit@3 0.727, MRR 0.665. A separate chunk-size sweep on one longer handbook document gave MRR 0.956 at 64 tokens, 0.968 at 128, 0.984 at 256 and 0.915 at 510. The challenge medians are close to the answerable ones, so the cosine gate separates the two sets only partly; the threshold is a trade-off between false refusals and wrong answers. The corpus is small and the questions were written by the project author, so these numbers show the harness and the gate work; they are not a benchmark.

Dense only versus sparse only versus hybrid (experiment E2, same questions and corpus; `python -m eka.eval --mode ...`):

| Mode | Hit@1 | Hit@3 | MRR |
|---|---|---|---|
| Dense only | 95.5% | 97.7% | 0.970 |
| Sparse only | 95.5% | 100% | 0.970 |
| Hybrid (fused) | 95.5% | 100% | 0.977 |

Hybrid is never worse, but the differences are about one question out of 44 on a 13-chunk corpus, so this does not show that hybrid helps. Run the evaluator with the worker stopped: one dense run failed when the worker and the evaluator competed for the same ingestion queue.

### Live-model answers

The same 44 questions through `POST /api/v1/chat` with `gpt-4o-mini` (verified mode), on the same 13 documents, run locally once:

| Check | Result |
|---|---|
| Expected fact in the answer, by string match | 36 of 44 |
| Expected fact in the answer, after reading the 8 misses | 43 of 44 (7 were correct paraphrases, such as "5" for `MAX_ATTEMPTS = 5`) |
| Answers marked verified, none unverified | 44 of 44 |
| Expected document among the citations | 42 of 44 |
| Wrong refusals | 1 (q31, the postmortem deadline, answered "I could not find this") |
| Wrong citation | 1 (q29 gave the right answer but cited `RetryPolicy.java`, not `incident_response.md`) |
| Latency, whole request | median 3.3 s, slowest-but-one 3.9 s |

Both defects were then traced and fixed (2026-11-11), and checked again with the offline extractive model, not with `gpt-4o-mini`:

- **q31 (wrong refusal).** The best passage scored cosine 0.526, under the 0.55 gate, so the model was never asked. The sweep (below) shows 0.50 refuses no answerable question on either evaluation set, so the default is now 0.50. Cost: on the main set the gate now stops 2 of 10 unanswerable questions instead of 3; the model's own refusal has to catch the third. That has not been checked with a live model.
- **q29 (wrong citation).** Retrieval was right (`incident_response.md` was passage 1); the model cited passage 2. The check only tested that citation numbers exist. A word-overlap check now rejects a citation when the cited passage covers less than half of the sentence's content words and another passage covers at least half and twice as many. In verified mode the model is asked once more, otherwise the answer is withheld as unverified ([`grounding.py`](src/eka/services/grounding.py)).
- End-to-end rerun through the API (`python -m eka.tools.answer_run`, fake extractive model, real embeddings and database): q31 answered, q29 cites `incident_response.md`, and the new check rejected none of the 44 answers. This shows the check does not reject plain extractive answers; it does not show how often it catches or wrongly rejects a real model's paraphrases.

**Rerun after the fixes (2026-11-13, P10-A).** Same 44 questions plus the 10 challenge questions, same 13 documents, `gpt-4o-mini`, verified mode, gate 0.50 and the citation check on:

| Check | First run (2026-11-10) | Rerun (2026-11-13) |
|---|---|---|
| Expected fact, by string match | 36 of 44 | 36 of 44 |
| Expected fact, after reading every miss | 43 of 44 | 44 of 44 (all 8 misses were correct paraphrases, e.g. "200 milliseconds" for `INITIAL_DELAY_MS = 200`) |
| Expected document among the citations | 42 of 44 | 44 of 44 |
| Wrong refusals | 1 (q31) | 0 (q31: "within 5 business days", cites `incident_response.md`) |
| Wrong citations | 1 (q29) | 0 (q29 cites `incident_response.md`) |
| Challenge (unanswerable) questions refused | not run | 10 of 10 (by the gate or the model's own `INSUFFICIENT_EVIDENCE`) |
| Latency, whole request | median 3.3 s | median 1.3 s (p50 1.1 s, p95 2.0 s from the usage report) |
| Time to first token (provider) | not measured | p50 851 ms, p95 1,248 ms |
| Tokens and cost, 54 requests | not recorded | 47,156 prompt + 913 completion tokens, 0.0076 USD (about 0.014 USD per 100 questions at 0.15 / 0.60 USD per million tokens; prices configured for the run, not built in) |

Both fixes hold with the real model and nothing that was right before went wrong. Still one run with one model on a small set; the latency gap between the two runs is network and provider variance, not a code change.

All 44 answers of the rerun were then hand-scored against their source files (2026-11-18; the 8 misses read earlier, the other 36 now): 44 correct, 0 partial, 0 wrong, 44 grounded in the expected document; rubric and per-question table in [`eval/reports/live_p10a_hand_scoring.md`](eval/reports/live_p10a_hand_scoring.md). The first run's 43 of 44 was after reading its misses only. One reader who also wrote the questions, one run, one model, short single-fact questions: a sanity check, not a benchmark.

**Triage agent, live run with log search (2026-11-13, P11).** Compose stack (core, worker, Prometheus, Alertmanager, Loki and Alloy, agent, mail catcher), `gpt-4o-mini`, a real fault: the database stopped for about a minute.

- Two reports were emailed, 0 failed (agent counters: 2 accepted, 2 sent, 0 failed, 0 pending).
- `EkaTargetDown` went the whole real path, Prometheus to Alertmanager to agent to email (the edge was not running). Tool calls: runbook, serviceHealth, `searchLogs` for core and for edge.
- `EkaHighErrorRate` was posted by hand. Tool calls: runbook, serviceHealth, PromQL, `searchLogs`. The report named the database as the likely cause from the real `/health/ready` 503.
- **Gap found.** Every `searchLogs` call asked for `ERROR` and got no lines, because the core logs database failures at WARNING level; Loki held 22 matching warning lines. The report was right from health and metrics, not from logs. **Fixed the same day:** a level word (`ERROR`, `WARN`, `WARNING`) now searches for warnings and worse at any level name (Loki `|~ "ERROR|WARN|CRITICAL|FATAL"`, CloudWatch `?"ERROR" ?"WARN" ...`); other text still matches literally. The tool description had itself suggested `ERROR`. Rerun of the same outage: the same `api | ERROR` call returned the failure lines, and the report quoted `WARNING: readiness check failed: TimeoutError` as evidence.
- An earlier attempt with the agent pointed at the edge-profile core name reported the core "unreachable", a wrong diagnosis caused by the test setup, not the code.

Triage agent with `gpt-4o-mini`, one synthetic `EkaHighErrorRate` alert, mail to the local catcher: the agent made 3 read-only calls (runbook, service health, one PromQL query) and sent a report in about 11 s. The core and edge were not running in that test, so the tools correctly reported them unreachable; the report's guess of "database issues" was the model's own and wrong (the database was up), which is why the report says to check the evidence before acting. One run; real email delivery was not tested.

### Query prefix (experiment E5)

BGE recommends putting `Represent this sentence for searching relevant passages: ` before each query. Same questions and corpus, `python -m eka.eval --query-prefix ...` (reports are written to `eval/reports/`, which is not committed):

| Set | Prefix | Hit@1 | MRR | Answerable cosine min / median | Unanswerable median | Wrong refusals at 0.50 / 0.55 |
|---|---|---|---|---|---|---|
| Main (13 docs, 44 q) | none | 95.5% | 0.977 | 0.526 / 0.710 | 0.571 | 0.0% / 2.3% |
| Main | BGE prefix | 95.5% | 0.977 | 0.484 / 0.691 | 0.549 | 2.3% / 4.5% |
| Handbook (1 doc, 41 q) | none | 97.6% | 0.984 | 0.545 / 0.656 | 0.577 | 0.0% / 2.4% |
| Handbook | BGE prefix | 100.0% | 1.000 | 0.519 / 0.635 | 0.549 | 0.0% / 14.6% |

The prefix changes ranking by one question on one set and lowers every cosine, so the refusal gate would need recalibrating. It stays off (`EKA_EMBEDDING_QUERY_PREFIX`, empty by default). Small sets written by the author; not a benchmark.

### Provider comparison (pipeline check, 2026-11-11)

The 44 questions and 10 challenge questions through `POST /api/v1/chat`, verified mode, same 13 documents. Without an AWS account, the second column comes from the real Bedrock adapter and boto3 pointed at the local stand-in with fake keys:

| Measure | Offline model | Bedrock adapter + local stand-in |
|---|---|---|
| Fact found, by string match (of 44) | 32 | 32 |
| Expected document cited | 42 | 42 |
| Wrong refusals | 1 | 1 |
| Unanswerable refused (of 10) | 3 | 3 |
| Median seconds per answer | 0.08 | 0.09 |

Equal scores are expected: the stand-in answers with the same offline model. The table shows that requests are signed, sent, parsed (including the event stream) and scored end to end; it says nothing about model quality. For the real comparison, set `EKA_CHAT_PROVIDER=bedrock`, the model id and the region, leave `EKA_BEDROCK_ENDPOINT_URL` empty and use real AWS credentials. No code changes.

### Added in P10 to P12

- **Token, cost and time to first token** (ADR-037): real provider token counts, cost from configured per-million prices (empty when none), TTFT, `eka_llm_*` series without user labels, admin usage report and an Admin page in the UI.
- **Model fallback** (ADR-038): `EKA_CHAT_FALLBACKS` (one fallback), a per-model circuit breaker, failover only before the first text; alert `EkaLlmFailoverBurst`.
- **Agent delivery tracking**: retries, sent/failed/pending counters, alerts `EkaTriageReportFailed` and `EkaTriageReportStuck`; drilled with a failing mail server.
- **Agent failure after an accepted alert** (D1.1.6): every accepted alert ends as a sent report or a counted failure. A model error, a missing model or an investigation past 3 minutes gives a runbook-only report; a report that cannot be sent is retried, counted as failed (`EkaTriageReportFailed`) and followed by a short "triage failed" notice; accepted batches are kept in a journal file until finished, so a restart completes them (`eka_ops_alerts_recovered_total`). 92 agent tests (12 new, one per failure path); `scripts/triage_failure_drill.sh` injects model-down, mail-down and a crash leftover against the real jar and a local mail catcher: 14 of 14 checks passed ([runbook](docs/runbooks.md)). Not covered: the AWS deployment keeps no journal (no volume), and the notice uses the same mail server as the report.
- **Readiness** waits for the embedding model; **traces** (NFR-07): set `EKA_OTEL_ENDPOINT` (core) and `EKA_EDGE_OTEL_ENABLED=true` (edge); `docker compose --profile monitoring up -d jaeger`, UI on 16686. Spans never carry text, keys or user ids. Verified end to end on 2026-11-12: one request through the edge showed edge, core and SQL spans in one Jaeger trace (statements parameterised, no token or user name in any attribute). The SQL instrumentation package pins SQLAlchemy below 2.1, so `tracing.py` skips its version check; a test guards that statements still produce spans.

### Added in P13 and P14 (code and Terraform, never applied)

- **Shared rate limit:** the edge counts per user in Redis when `EKA_EDGE_RATE_LIMIT_REDIS_URL` is set (one Lua script, Redis clock), so several edge tasks share one limit; fails open if Redis is down. Tested against a real Redis: two edge instances allowed 5 of 10 requests together, where in-memory counting allows 10.
- **AWS hardening (`infra/aws`):** autoscaling of the api service (2 to 4 tasks), ElastiCache with TLS, WAF (managed rules and a per-address rate rule), GitHub OIDC deploy role and a manual deploy workflow, CloudWatch alarms named after the alert rules.
- **Triage agent on AWS:** its own Fargate service with no inbound port; CloudWatch alarms reach it through SNS and an SQS queue it polls (`OPS_AGENT_ALARM_QUEUE_URL`), parsed into the same alerts Alertmanager sends. Tested with a stand-in SQS client; a test checks every alarm name has a runbook section.

### Added in P16

- **Web fallback follows links** (ADR-039, off unless `EKA_WEB_MAX_LINKED_PAGES` is 1 to 20): when an entry page is fetched, up to that many pages it links to are fetched too. One level only, only under the entry page's directory on the same host, only if the host's robots.txt allows the agent `eka-web-fallback` (unreadable robots.txt: no links), all through the same guarded fetcher. Checked live against docs.python.org: with the tutorial index as the only entry URL, a question about default argument values was answered with a citation to the linked `controlflow.html` (fake chat model).
- **Local logs to CloudWatch** (ADR-040): `docker compose --profile cloudwatch up -d localstack log-shipper` starts Vector, which ships this project's container logs to CloudWatch Logs with the AWS stream names (`eka/core/<id>`). Alloy has no CloudWatch writer, so Vector runs next to it. Checked against LocalStack: the triage agent's CloudWatch search found the shipped lines (`ShippedLogsLiveTest`). Not tried against real AWS.
- **Browser test in CI** (ADR-041): a Playwright test signs in, uploads a file, waits for `ready`, checks a cited answer and a refusal, and signs out, against a real core with the fake model (`ui/e2e`, CI job `ui-browser`). It found a login bug: a wrong key was stored before it was checked, which sent it twice. Fixed.

### Not done

| Item | Note |
|---|---|
| Reranking on by default | Evaluated on 96 questions (D1.2.5): better ranking, but p95 1.1 to 1.5 s against a 500 ms limit on a laptop CPU. Stays off; revisit with a GPU, a smaller `EKA_RERANKER_TOP` or a larger real corpus |
| Independent scoring of live answers | All 44 were hand-scored by the author (see above); no second reader, no larger or harder question set |
| Other models and the real cross-provider table | Only `gpt-4o-mini` was run live; the comparison pipeline is ready and needs Bedrock access (an AWS account and approval of the spend) |
| Entra ID or other hosted identity provider | Tested against Keycloak only |
| Real email delivery | Verified only into a local mail catcher; real SMTP not tried |
| Logs on AWS | The Terraform sends container logs to CloudWatch and the triage agent searches them (`OPS_AGENT_CLOUDWATCH_LOG_GROUP`), tested against LocalStack only. The agent's Terraform and the alarm queue are validated, not applied; nothing ran on real AWS. Locally, logs reach CloudWatch through the Vector shipper (LocalStack only) |
| Web fallback: search and crawling | Entry URLs plus one level of links in the same directory (ADR-039); no search engine and no deeper crawling. Run only with the fake model so far. A page that the worker has not indexed within 30 s is used from the next question on |
| Real Bedrock call, real AWS deployment | Needs an AWS account; the adapter has run end to end only against the local stand-in, and the Terraform (including WAF, autoscaling, alarms, the agent service and the deploy workflow) is validated only |
| Browser test coverage | The `ui-browser` job (API-key build) passes on GitHub Actions (CI run 43393823859). The single sign-on build has no browser test |

## Tech stack

- **Core:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy 2 (async) over psycopg 3, Alembic, PostgreSQL 17 with pgvector, fastembed (BGE-small embeddings, optional cross-encoder), `pypdf` and `python-docx`, boto3 (S3 and Bedrock); pytest with Testcontainers, Ruff, mypy.
- **Java 21 and Spring Boot:** the edge on Spring Cloud Gateway with Resilience4j; the triage agent with LangChain4j.
- **UI:** Angular 22 with Vitest.
- **Platform:** Docker Compose with Keycloak, Prometheus, Alertmanager, Grafana, Loki and Alloy; GitHub Actions; Terraform for AWS.

There is no orchestration framework in the core; LangChain is admitted only if a specific need appears ([ADR-002](docs/adr/ADR-002-no-orchestration-framework.md)).

## Documentation

| Document | Contents |
|---|---|
| [Business requirements](docs/BRD.md) | Business outcomes, scope, functional and non-functional requirements with status, acceptance criteria, risks |
| [Decision records](docs/adr/README.md) | One file per architecture decision with options, cost, risk and review trigger |
| [Runbooks](docs/runbooks.md) | SLOs, one runbook per alert, backup and restore procedure |
| [Docker guide](docs/DOCKER_GUIDE.md) | Images per Compose profile, start, stop and clean-up |
| [OpenAPI snapshot](docs/openapi.json) | The committed API contract; a test fails if the code and this file differ |
| [Postman collection](postman/eka.postman_collection.json) | Contract checks for authentication, authorization, errors and the main flows |

## Quick start

Requires Python 3.11 or newer and Docker (for the database).

1. Create the environment and install:

   ```powershell
   python -m venv .venv
   .venv\Scripts\python -m pip install -e ".[dev]"
   ```

   On macOS or Linux: `python -m venv .venv`, `source .venv/bin/activate`, `pip install -e ".[dev]"`.

2. Create your settings file. Copy `.env.example` to `.env` (git-ignored), set `EKA_DB_PASSWORD`, and repeat that password inside `EKA_DATABASE_URL`. Then create an API key and its digest:

   ```bash
   python -m eka.tools.hash_key --generate
   ```

   The command prints the key once (keep it in your own secret store) and its SHA-256 digest. Put the digest in `EKA_API_KEYS` (see `.env.example`). The service never stores the key itself.

3. Start the database and apply the schema:

   ```bash
   docker compose up -d db
   alembic upgrade head
   ```

4. Run the API:

   ```bash
   python -m eka
   ```

   `python -m eka` also works on Windows, where plain `uvicorn` would pick an event loop the database driver cannot use.

5. Check it:

   ```bash
   curl http://127.0.0.1:8000/health/ready
   curl -H "X-API-Key: <your key>" http://127.0.0.1:8000/api/v1/me
   ```

   Interactive docs are at http://127.0.0.1:8000/docs.

## Checks (the same ones CI runs)

With the virtual environment active (on Windows without activation, prefix each command with `.venv\Scripts\python -m`):

```bash
ruff check .
ruff format --check .
mypy src tests
python -m eka.tools.export_openapi --check
pytest -m "not integration"      # offline tests, no Docker needed
pytest --cov=eka --cov-fail-under=85   # everything; integration tests start a throwaway PostgreSQL and skip if Docker is off
(cd gateway && mvn -B verify)     # edge
(cd ops-agent && mvn -B verify)   # triage agent
(cd ui && npx ng test --watch=false && npx ng build)
scripts/restore_drill.sh          # backup, restore to scratch, compare (stack running)
```

Alert rules: `promtool test rules monitoring/alerts.test.yml` (CI runs it in the `prom/prometheus` image).

If you change the API on purpose, regenerate the snapshot with `python -m eka.tools.export_openapi` and review the diff.

## Docker

```bash
docker compose up --build        # database, migration, API and worker
curl http://localhost:8000/health/ready
```

Compose needs the settings from `.env` (it refuses to start without `EKA_DB_PASSWORD` and `EKA_API_KEYS`). The image runs as a non-root user, writes JSON logs and defaults to `EKA_ENVIRONMENT=prod`, which hides the API docs; Compose sets `local` so `/docs` stays available. A one-shot `migrate` service applies the schema before the API and the worker start. Optional profiles (`edge`, `idp`, `monitoring`, `agent`, `cloudwatch`) are listed in the [Docker guide](docs/DOCKER_GUIDE.md). The database port is published on `127.0.0.1` only, for local use.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `EKA_ENVIRONMENT` | `local` (`prod` in the image) | `local`, `test` or `prod`; `prod` hides `/docs`, `/redoc` and `/openapi.json`. Outside `test` the settings below are required and startup fails without them |
| `EKA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `EKA_LOG_JSON` | `false` (`true` in the image) | One JSON object per log line |
| `EKA_DATABASE_URL` | none (required) | `postgresql+psycopg://user:password@host:port/database`; treated as a secret |
| `EKA_AUTH_MODE` | none (required) | `api_key` (the core on its own) or `gateway` (behind the edge: only the edge's internal token is accepted; needs `EKA_GATEWAY_JWKS_URL`) |
| `EKA_API_KEYS` | none (required in `api_key` mode) | JSON object: `{"<user-id>": {"sha256": "<64 hex characters>", "role": "user"}}` with role `user` or `admin` |
| `EKA_DB_PASSWORD`, `EKA_DB_PORT` | none (required), `5432` | Used by `docker-compose.yml` for the database service |
| `EKA_WEB_FALLBACK_ENABLED` | `false` | Turns on the web fallback (ADR-030). Then `EKA_WEB_ALLOWED_HOSTS` (JSON list of exact host names) and `EKA_WEB_ENTRY_URLS` (JSON list of 1 to 10 https URLs on those hosts) are required; startup fails otherwise. Pages are refreshed after `EKA_WEB_REFRESH_HOURS` (24). `EKA_WEB_MAX_LINKED_PAGES` (0 to 20, default 0) also fetches that many pages linked from each entry page, one level deep in the same directory (ADR-039) |

The chat provider (fake, OpenAI-compatible or Bedrock), file storage, reranker and limits are listed with comments in `.env.example`. Settings come from environment variables or a git-ignored `.env` file (copy `.env.example`). Secrets are supplied the same way and never committed.

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health/live` | none | The process is up |
| GET | `/health/ready` | none | Ready for traffic: the database answers (503 otherwise); returns the build version |
| GET | `/api/v1/me` | caller | The caller's user id and role (behind the edge, answered by the edge) |
| GET, POST, DELETE | `/api/v1/documents`, `/api/v1/documents/{id}` | caller | Upload (202 new, 200 same bytes), list, inspect (polling path for ingestion), delete |
| POST | `/api/v1/search` | caller | Hybrid retrieval with filters, owner-scoped. `scores.rerank` is the cross-encoder score when `EKA_RERANKER_MODEL` is set, otherwise `null` |
| POST | `/api/v1/chat` | caller | Cited answer as JSON, or as a stream with `"stream": true` |
| GET, DELETE | `/api/v1/conversations`, `/api/v1/conversations/{id}` | caller | Conversation history |
| GET | `/api/v1/admin/status`, `/api/v1/admin/metrics` | admin | Build info; Prometheus metrics |
| GET | `/api/v1/admin/usage`, `/api/v1/admin/documents` | admin | Token, cost and latency usage by user or day (window up to 92 days); document counts by status across all users |

"Caller" depends on `EKA_AUTH_MODE`: in `api_key` mode an `X-API-Key` header; in `gateway` mode (behind the edge) a bearer internal token from the edge, and `X-API-Key` is ignored. The 401 detail text says "A valid API key is required." in both modes.

**Isolation unit is the owner, not a tenant.** Every document, chunk and conversation has an `owner_id`; another owner's id returns 404 and search never returns foreign chunks. Behind the edge the owner is a pseudonym of the identity provider's `iss` + `sub`. There is no tenant model and no service-account client in the bundled Keycloak realm, so a machine caller serving several tenants needs one identity per tenant.

The full contract is in `docs/openapi.json`. `postman/eka-crud.postman_collection.json` is a hands-on collection (documents and conversations create, read, list, delete; search; chat; admin; error cases) with its own environment file; run it from the repository root against a running stack. Behind the edge, the key is replaced by a bearer token.

Errors use `application/problem+json` with a `request_id` that matches the `X-Request-Id` response header and the log line.

## Project layout

```text
src/eka/
  main.py             app factory and composition root (the only place adapters are chosen)
  config.py           typed settings with startup validation
  runtime.py          process runner used by `python -m eka`
  request_context.py  request id, user id and the access log line
  logging_config.py   text or JSON logs
  domain/             models and typed errors; imports nothing else
  ports/              repository interfaces (owner_id is always the first argument)
  security/           API-key and edge-token authentication
  services/           retrieval, answering, citation grounding check
  ingestion/          file sniffing, parsers, cleaning, chunking
  eval/               retrieval evaluation harness and CI gate
  api/                routers, dependencies, the problem+json handler
  adapters/db/        engine and row-level-security session, table models, repositories
  tools/              hash_key, sync_admin_key, export_openapi, loadtest, answer_run, compare_runs, bedrock_stub
  adapters/web_fetch.py  guarded HTTPS fetcher for the optional web fallback
gateway/              Java 21 edge (Spring Cloud Gateway)
ui/                   Angular web UI
ops-agent/            incident triage agent (Java 21, LangChain4j): webhook, read-only tools, report email
monitoring/           Prometheus rules and tests, Alertmanager, Grafana, Loki and Alloy configuration
infra/aws/            Terraform for an AWS deployment (validated, never applied)
keycloak/             test realm for the identity provider profile
scripts/              database backup, restore, restore drill, Keycloak end-to-end check
alembic/              migrations (roles, tables, indexes, row-level security)
docs/openapi.json     committed API contract
tests/                offline tests; tests/integration needs Docker
```

## Web UI

An Angular app in `ui/` with document upload and status, and chat with streamed answers and
citations. How it signs in is chosen when it is built or served:

| Mode | Start | Talks to |
|---|---|---|
| API key (default) | `docker compose up -d`, then `cd ui && npm ci && npm start` | the core on :8000 |
| Single sign-on | `docker compose --profile edge --profile idp up -d --build`, then `cd ui && npm ci && npm run start:sso` | Keycloak on :8180, the edge on :8080 |

Both serve http://localhost:4200. For single sign-on, add `127.0.0.1 keycloak` to the hosts file:
Keycloak always issues tokens as `http://keycloak:8180`, the issuer the edge checks. Sign in as
`alice` or `boss` with the passwords from `.env`. The browser uses the authorization code flow with
PKCE, without a client secret or a library (`ui/src/app/oidc.ts`). If the Keycloak container existed
before 2026-11-11, recreate it once (`docker compose --profile idp up -d --force-recreate keycloak`)
so the realm with the sign-out redirect and refresh token rotation is imported. The test users
have fixed ids there, so recreating Keycloak does not change which documents they see.

Tests: `npm test` (39). Browser test (Docker and Chromium; starts its own core in the compose project `eka-e2e`):

```bash
ui/e2e/stack.sh up
cd ui && npx playwright install chromium && E2E_API_KEY=$(cat e2e/.stack.key) npx playwright test
cd .. && ui/e2e/stack.sh down
```

 The API key or tokens stay in `sessionStorage` for the tab only. The access
token lives 15 minutes; when it has expired, the app swaps the refresh token for a new pair before
the next request, and a timer renews it a minute before it expires so an open page never sends an expired one (one renewal shared by the timer and concurrent requests). Keycloak rotates refresh tokens and
ends the session after 30 idle minutes or 8 hours; then the renewal fails and you sign in again.
A Keycloak container created before this change must be recreated once to import these settings.

## Postman collection

`postman/eka.postman_collection.json` checks authentication, authorization, the error format and the
metrics endpoint, plus search, chat and documents when a database is available. The key variables
in `postman/local.postman_environment.json` are empty; pass them with `--env-var` or fill them in
Postman. CI runs the database-free folders against a core started in test mode.

## License and AI use

No open-source license is granted: all rights reserved. Use of this repository for AI or ML training, AI-based analysis or reproduction, or inclusion in datasets is not permitted without written permission: see [AI_USE_POLICY.md](AI_USE_POLICY.md).

Canary: `eka-canary-2a4a885ea917479dadc1` (a unique marker used to detect copies of this repository; see [AI_USE_POLICY.md](AI_USE_POLICY.md)).
