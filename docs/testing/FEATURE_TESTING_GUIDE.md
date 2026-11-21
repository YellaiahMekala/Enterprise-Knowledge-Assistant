# EKA: feature testing guide

Scope: the main features of the service and what each test set proves. Numbers come from the README "Built and checked"
section, the runbooks and local runs on 2026-11-18 and 2026-11-19 (F19 to F25 were added on 2026-11-19, in the order: results table, why it was built this way, trade-offs, limits, pending). Where a feature was only checked locally, the guide says so.
CI means the GitHub Actions workflow `.github/workflows/ci.yml`. A CI run number or date is quoted only where the README
already records it.

Run types:

- **Default**: no Docker, no network, no model call. `pytest -m "not integration"` (core) and `mvn -B verify` (edge, agent).
- **Integration**: needs Docker (PostgreSQL with pgvector, S3-compatible server). `pytest -m integration`.
- **Stack drill**: a script or manual run against the Compose stack or the built jar. Local only.
- **Live model**: real `gpt-4o-mini` calls, approved spend, local only, never in CI.

Secrets are environment variables, never written in this guide.

## Index

| ID | Feature | Run type | In CI |
|---|---|---|---|
| [F1](#f1-core-api-authentication-isolation) | Core API, authentication, isolation | default + integration | yes |
| [F2](#f2-ingestion-and-retrieval) | Ingestion and retrieval | default + integration | yes |
| [F3](#f3-cited-chat-refusal-gate-grounding-check) | Cited chat, refusal gate, grounding check | default | yes |
| [F4](#f4-retrieval-evaluation-gate) | Retrieval evaluation gate | integration | yes |
| [F5](#f5-live-model-answers-and-hand-scoring) | Live answers and hand scoring | live model | no |
| [F6](#f6-java-edge-gateway) | Java edge | default (Maven) | yes |
| [F7](#f7-model-fallback-and-token-accounting) | Model fallback, token and cost accounting | default | yes |
| [F8](#f8-incident-triage-agent) | Incident triage agent | default (Maven) | yes |
| [F9](#f9-triage-failure-drill-d116) | Triage failure drill (D1.1.6) | stack drill | no |
| [F10](#f10-observability-and-alerts-as-code) | Observability and alerts as code | default + stack | partly |
| [F11](#f11-web-ui-and-browser-test) | Web UI and browser test | default + stack | yes |
| [F12](#f12-api-contract-and-postman) | API contract and Postman | default + Postman CLI | yes |
| [F13](#f13-backup-and-restore-drill) | Backup and restore drill | stack drill | no |
| [F14](#f14-web-fallback-and-providers) | Web fallback, Bedrock stand-in | default | yes |
| [F15](#f15-reranking-study-d125) | Reranking study (D1.2.5) | default + integration DB | no |
| [F16](#f16-live-triage-agent-and-web-fallback-pq123) | Live triage agent and web fallback (PQ1.2.3) | live model + stack | no |
| [F17](#f17-deploy-step-and-alarm-queue-on-localstack-pq125) | Deploy step and alarm queue on LocalStack (PQ1.2.5) | stack drill | no |
| [F18](#f18-admin-key-and-digest-consistency) | Admin key and digest consistency | default | yes |
| [F19](#f19-edge-interop-fixtures-stale-token-files) | Edge interop fixtures (stale token files) | default + Maven | yes |
| [F20](#f20-edge-rate-limit-shared-redis-limiter-and-the-40-parallel-burst) | Edge rate limit, shared Redis limiter, 40-parallel burst | default + stack | partly |
| [F21](#f21-eka-identity-in-the-platform-login-test-int-3-and-the-admin-key) | EKA identity in the platform login test (INT-3) | stack drill | no |
| [F22](#f22-aws-deployment-code-terraform-for-ecs-and-what-has-not-run) | AWS deployment code (Terraform for ECS) | validate only | yes (validate) |
| [F23](#f23-copyright-and-canary-headers-view-only-policy) | Copyright and canary headers, view-only policy | file check | n/a |
| [F24](#f24-test-counts-lint-and-types-2026-11-19) | Test counts, lint and types | default | yes |
| [F25](#f25-link-following-local-log-shipping-to-cloudwatch-and-the-browser-test-p16-2026-11-13) | Link following, CloudWatch log shipping, browser test | default + stack | partly |

## F1 Core API, authentication, isolation

**What it proves.** A user sees only their own documents, in the code (owner-scoped repositories) and in the database
(row-level security that fails closed). Both API-key mode and edge-token mode refuse bad credentials. Bad requests give
`problem+json` with a request id.

**Tests.** Default: `test_auth.py`, `test_gateway_auth.py`, `test_route_auth.py`, `test_errors.py`, `test_settings.py`,
`test_health.py`, `test_architecture.py` (layering rules), `test_edge_interop.py` (tokens minted by the real edge verify in
the core). Integration: `tests/integration/test_rls.py`, `test_leakage.py`, `test_repositories.py`, `test_migrations.py`.

**How to run.**

```bash
pytest -m "not integration"      # no Docker
pytest -m integration            # needs Docker
```

**Expected.** All green. On 2026-11-18 the default set gave 594 passed, 5 skipped, 2 failed (stale interop fixtures, see F19). After regenerating them on 2026-11-19: 612 passed, 5 skipped, 79 deselected without Docker, and 691 passed, 5 skipped with Docker (F24). The full
suite on 2026-11-11 (with Docker) gave 616 passed, 5 skipped, coverage 91.1% (gate 85%).

**Failure modes.**

- `test_edge_interop.py` reads tokens that the edge test run writes to `gateway/target/interop`. If that folder is older
  than the one-hour test leeway, two tests fail. This is a stale fixture, not a product bug: run `mvn -o -q -B test` (or `mvn -B verify`) in
  `gateway/` to rewrite it, or delete the folder (the module then skips). Details in F19.
- A half-configured start (missing secret) is refused by `test_settings.py` on purpose.

**Talking points.** Isolation is enforced twice (repository contract and RLS), so one forgotten filter does not leak. The
leakage tests search as user B for user A's text and expect nothing.

## F2 Ingestion and retrieval

**What it proves.** Files (PDF, DOCX, CSV, code, text) are validated by content, chunked on page or section bounds,
embedded locally and searchable by dense vectors and full text fused by reciprocal rank.

**Tests.** Default: `test_loaders.py`, `test_sniff.py`, `test_chunking.py`, `test_cleaning.py`, `test_parse_runner.py`,
`test_processing.py`, `test_documents_api.py`, `test_documents_service.py`, `test_retrieval_service.py`,
`test_storage_local.py`, `test_storage_s3.py`. Integration: `test_ingestion_flow.py`, `test_ingestion_queue.py`,
`test_search_database.py`, `test_storage_s3_server.py`. Opt-in model test: `tests/model/test_real_embedder.py`
(set `EKA_TEST_REAL_MODEL=1`; 2 tests skip otherwise).

**How to run.** As F1. For the real embedding model: `EKA_TEST_REAL_MODEL=1 pytest tests/model`.

**Expected.** Green. A DOCX, a CSV and a Java file went through the Docker stack on 2026-11-11 and were answered with
section, row and line citations.

**Failure modes.** A file whose content does not match its extension is rejected. Running the evaluator while the worker
runs once made a dense run fail, because both competed for the queue (README note).

**Talking points.** Queue in PostgreSQL (ADR-010) instead of a broker: one fewer moving part, tested with real
concurrency. Local BGE-small embeddings keep documents inside the system.

## F3 Cited chat, refusal gate, grounding check

**What it proves.** Answers carry server-built citations. If the best passage is below the similarity gate (0.50), the
model is not asked and the answer is a `weak_evidence` refusal. A word-overlap check rejects a citation that points at
the wrong passage.

**Tests.** `test_chat_api.py`, `test_answering.py`, `test_grounding.py`, `test_prompt.py`, `test_chat_openai.py`.

**How to run.** `pytest tests/test_grounding.py tests/test_answering.py tests/test_chat_api.py`.

**Expected.** Green, offline (fake model). Both stream modes (verified, fast) are covered.

**Failure modes.** Lowering the gate answers weak questions; raising it refuses answerable ones (q31 at gate 0.55 was a
wrong refusal). A real model's paraphrases can fail the overlap check; fake-model tests cannot show how often (see F5).

**Talking points.** The model never builds a citation; the server does (ADR-008, ADR-036). The gate and the model's own
`INSUFFICIENT_EVIDENCE` are two layers, and the second one has to catch what the gate lets through.

## F4 Retrieval evaluation gate

**What it proves.** Retrieval quality does not regress: 44 questions on 13 documents with Hit@k, MRR and refusal checks
against `eval/thresholds.json`. The set is now 96 answerable questions (44 original, 52 synthetic, 33 labelled "hard") and 24 unanswerable.

**Tests.** `tests/test_eval_harness.py` (default), `tests/integration/test_eval_runner.py`; the CI job "evaluation" runs
`python -m eka.eval --check --out eval/reports/ci.md`.

**How to run.** `python -m eka.eval --check --out eval/reports/local.md` (needs the database; stop the worker first).

**Expected.** Exit code 0 and a report. Reports from the experiments are in `eval/reports/` (chunk size, dense vs sparse
vs hybrid, reranker, embeddings).

**Failure modes.** A drop below a threshold fails the gate. On a 13-chunk corpus, hybrid vs dense differs by about one
question, so it does not prove hybrid helps.

**Talking points.** The gate runs in CI (ADR-018). Be ready to say the corpus is small and written by the author.

## F5 Live model answers and hand scoring

**What it proves.** With `gpt-4o-mini`, the 44 questions plus 10 unanswerable ones: all 44 answers correct and grounded
after hand scoring, 10 of 10 refused, 0 wrong refusals, 0 wrong citations; cost 0.0076 USD for 54 requests.

**Tests.** `python -m eka.tools.answer_run` writes the answers file; scoring is by reading. Evidence:
`eval/reports/live_p10a_gpt-4o-mini.jsonl` and `eval/reports/live_p10a_hand_scoring.md` (rubric and per-question table).

**How to run.** Needs the OpenAI key in the environment (see `.env.example` for the variable name) and approved spend. Not
for CI.

**Expected.** A jsonl with one row per question: answer, cited documents, refusal reason, verified flag, seconds.

**Failure modes.** String match undercounts (8 of 44 misses were correct paraphrases, such as "200 milliseconds" for
`INITIAL_DELAY_MS = 200`). Scoring by one reader who wrote the questions is not independent.

**Talking points.** Two defects from the first run (q31 refusal, q29 citation) were traced, fixed and confirmed by a
rerun. Honest limit: single-fact questions, one model, one run.

## F6 Java edge gateway

**What it proves.** The Spring Cloud Gateway edge validates identity-provider tokens, swaps them for a 60-second internal
token, rate-limits per user, audits, passes SSE through, cancels on client disconnect and returns a fast 503
`circuit-open` when the core hangs.

**Tests (47).** `EdgeContractTest`, `UpstreamErrorMappingTest`, `CircuitBreakerTest`, `UpstreamFailureDrillTest`,
`RateLimitTest`, `RedisRateLimiterTest` (real Redis), `ManagementEndpointsTest`, `InteropFixtureTest`,
`StreamingSpikeS1Test` (in `gateway/src/test`).

**How to run.** `cd gateway && mvn -B verify`.

**Expected.** 47 tests, 0 failures (CI run 43393823859 per README).

**Failure modes.** The first CI run failed because a hung fake core stalled later tests; fixed in the fixture.

**Talking points.** Hung-core drill: the breaker opens after repeated timeouts and its state is exported as a metric.

## F7 Model fallback and token accounting

**What it proves.** On a provider failure before the first token, the answer fails over to a second model; a per-model
breaker stops hammering a dead model. Token counts and cost come from the provider, TTFT is recorded, and metrics carry no
user labels.

**Tests.** `test_chat_fallback.py`, `test_failover_drill.py`, `test_usage_accounting.py`,
`tests/integration/test_usage_database.py`, `test_admin_api.py`.

**How to run.** `pytest tests/test_chat_fallback.py tests/test_failover_drill.py tests/test_usage_accounting.py`.

**Expected.** Green with fakes and the Bedrock stand-in; no paid call.

**Failure modes.** Failover after the first text would show a mixed answer, so it is not done. Prices are configuration;
empty prices give no cost.

**Talking points.** Cost per 100 questions was about 0.014 USD on `gpt-4o-mini` at the configured prices.

## F8 Incident triage agent

**What it proves.** An Alertmanager webhook leads to a read-only investigation (PromQL, service health, runbook, log
search) and an emailed report, behind a token, a call budget and an audit log; without a model it sends a runbook-only
report.

**Tests (92 in the module).** `TriageServiceTest` (full tool loop with a scripted model), `OpsToolsTest`,
`PromQlGuardTest`, `LogSearchTest`, `CloudWatchLogStoreTest`, `RunbookReaderTest`, `ReportFormatterTest`,
`ReportDeliveryTest`, `ReportDeliveryFailureTest`, `SqsAlarmPollerTest`, `AwsAlarmsMatchRunbooksTest`,
`AlertWebhookControllerTest`. Live ones (`LogSearchLiveTest`, `CloudWatchLogStoreLiveTest`, `ShippedLogsLiveTest`) skip
unless an endpoint is set.

**How to run.** `cd ops-agent && mvn -B verify`. For the live tests, set the Loki or LocalStack endpoint first.

**Expected.** 92 tests green (README, after D1.1.6; the earlier CI run recorded 80 with 7 skipped).

**Failure modes.** The guard refuses PromQL that is not a read query. In one live run the model guessed "database issues"
while the database was up, which is why the report tells the reader to check the evidence.

**Talking points.** Read-only tools with a call budget (ADR-033). The first live run found that log search asked for ERROR
while failures log at WARNING; fixed with `LogLevels` and rerun.

## F9 Triage failure drill (D1.1.6)

**What it proves.** An accepted alert always ends as a sent report or a counted failure, even when the model, the mail
server or the process fails.

**Design.** A 3-minute investigation cutoff (`OPS_AGENT_INVESTIGATION_TIMEOUT`) gives a runbook-only report. A report that
cannot be sent is retried, counted (`EkaTriageReportFailed`) and followed by a short "triage failed" notice. Accepted
batches sit in a journal file until finished; a restart completes them (`eka_ops_alerts_recovered_total`). A missing
recipient counts as failed.

**Tests.** 12 new unit tests, one per failure path, in the ops-agent module (for example `ReportDeliveryFailureTest`).
Drill: `scripts/triage_failure_drill.sh`.

**How to run.**

```bash
(cd ops-agent && mvn -B package -DskipTests)
scripts/triage_failure_drill.sh              # all three scenarios
scripts/triage_failure_drill.sh smtp-down    # one scenario
```

Needs Java 21, curl and Docker (throwaway mail catcher). No model call, no cost.

**Expected.** Exit code 0 and 14 of 14 checks passed (2026-11-18, local, about 2 minutes).

| Scenario | Injected fault | Expected end state |
|---|---|---|
| `model-down` | model endpoint refuses connections | runbook-only report emailed; fallback counter 1, failed 0 |
| `smtp-down` | mail server unreachable | failed counter 1, pending back to 0, nothing sent |
| `restart` | journal file left behind (as after a crash) | report emailed after next start; recovered counter 1; journal empty |

**Failure modes.** If the jar is not built the script cannot start. In `smtp-down` the notice cannot arrive either (same
mail server), so the page comes from Prometheus and Alertmanager's own mail path.

**Honest limits.** The AWS deployment keeps no journal (no volume). The notice shares the report's mail server. Real SMTP
not tried. CI after the change is green (run 44296520354, 2026-11-18).

**Talking points.** I asked "what happens to an alert after we answer 202?" and wrote one test and one injected fault per
answer. A counted failure with an alert beats silent loss.

## F10 Observability and alerts as code

**What it proves.** SLO recording rules and 4 alerts plus a watchdog are valid and fire on the right inputs; metrics are
exposed without user labels; traces carry no text, keys or user ids.

**Tests.** `promtool test rules` (5 cases, in the monitoring CI job), `test_tracing.py`, `test_loadtest.py`,
`AwsAlarmsMatchRunbooksTest`, `ManagementEndpointsTest`.

**How to run.** `promtool test rules` on the rule test file under `monitoring/` (exact command in `ci.yml`). Stack:
`docker compose --profile monitoring up -d`.

**Expected.** 5 of 5 alert cases pass. Watchdog drill with the agent stopped: email after 70 s. Real fault drill: core
stopped, `EkaTargetDown` fired, email in about 4 minutes.

**Failure modes.** SQL instrumentation silently did nothing on SQLAlchemy 2.1.8; fixed (`skip_dep_check`) and guarded by a
test.

**Talking points.** Alerts link to runbooks; the watchdog covers the case where the alert path itself is down.

## F11 Web UI and browser test

**What it proves.** Sign-in (API key, or Keycloak with PKCE), upload, streamed chat with citations, token refresh.

**Tests.** 39 Angular unit tests, `ui/e2e/smoke.spec.ts` (Playwright, CI job `ui-browser`), `scripts/keycloak_e2e.sh`
(7 checks).

**How to run.** `cd ui && npm ci && npx ng test --watch=false`. Browser: `bash ui/e2e/stack.sh up`, then Playwright (see the
CI job for the exact commands).

**Expected.** 39 of 39; 6 local browser passes at 14 to 23 s each; 7 of 7 Keycloak checks.

**Failure modes.** The browser job runs in GitHub Actions and is green (run 44296520354). A bug found by it:
login stored a key before checking it.

## F12 API contract and Postman

**What it proves.** The code-first OpenAPI snapshot matches the app, and the Postman collection passes against the stack.

**Tests.** `test_contract.py`, `python -m eka.tools.export_openapi --check` (CI), Postman collection (36 assertions).

**How to run.** `python -m eka.tools.export_openapi --check`; collection with the Postman CLI against the Compose stack
(see `ci.yml`).

**Expected.** No drift; 0 failed assertions.

## F13 Backup and restore drill

**What it proves.** A dump restores with the same migration version, row counts and row-level security.

**How to run.** `scripts/restore_drill.sh` (needs the Compose database).

**Expected.** Identical counts and policies; 8 s on local data.

**Failure modes.** Files in the storage volume are separate; restoring only the database leaves documents pointing at
missing files.

## F14 Web fallback and providers

**What it proves.** The allowlisted fetcher refuses private, loopback and metadata addresses, plain http and redirects off
the list; the Bedrock adapter signs and parses real Converse JSON through boto3 against a local stand-in.

**Tests.** `test_web_fetch.py`, `test_web_fallback.py`, `test_web_links.py`, `test_html_text.py`, `test_chat_bedrock.py`,
`test_bedrock_stub.py`, `test_answer_run.py`, `test_compare_runs.py`.

**How to run.** `pytest tests/test_web_fetch.py tests/test_web_fallback.py tests/test_web_links.py tests/test_chat_bedrock.py`.

**Expected.** Green offline. Live against docs.python.org: first answer in 14 s, the next in 0.1 s from the stored copy.

**Honest limits.** Never called real Bedrock or real AWS. Web fallback checked with the fake chat model only.

**Talking points.** SSRF defence: the fetcher connects to the address it checked and re-checks every redirect.

## F15 Reranking study (D1.2.5)

**What it proves.** Whether the optional cross-encoder should be on by default, decided by a rule written before the
run: MRR and Hit@3 no more than 0.01 lower, no more questions worse than better, p95 search at most 500 ms, median
added at most 250 ms, in every configuration. Result on 96 questions (synthetic, author-written), chunks of 256 and 64
tokens: quality better (MRR +0.028 and +0.035, paired intervals above zero), latency far over the limits (p95 1526 and
1079 ms), so reranking stays off ([ADR-032](../adr/ADR-032-optional-cross-encoder-reranking.md)).

**Tests.** `tests/test_rerank_study.py` (percentiles, bootstrap, nDCG, changed cases, decision rule, report),
`tests/test_retrieval_service.py` (hits carry the rerank score; the search response exposes it),
`tests/test_eval_harness.py` (question set size and labels).

**How to run.** Unit: `pytest tests/test_rerank_study.py tests/test_retrieval_service.py tests/test_eval_harness.py`.
Study: start a throwaway pgvector database, `alembic upgrade head`, then `python -m eka.eval.rerank_study` (about 10
minutes; local embedder and cross-encoder from `data/models`, no paid call, no language model). Report:
`eval/reports/e3_rerank_study.md`.

**Expected.** Unit tests green offline. The study writes the report and ends with a PASS or FAIL line per check.

**Honest limits.** One author wrote corpus and questions; the corpus is 13 short files. The intervals show noise over
these questions only. Latency is one laptop CPU with Docker running; a GPU or smaller `EKA_RERANKER_TOP` would change
it. The refusal gate (dense cosine) is not changed by reranking, and on the 24 unanswerable questions it lets 22
through at 0.50, so the model's own refusal carries most of the near-miss negatives.

**Talking points.** Set the decision rule before measuring; report both the quality gain and the latency cost; keep the
default off when the rule fails, and say why.

## F16 Live triage agent and web fallback (PQ1.2.3)

**What it proves.** With a live model against the Compose stack: four alerts (3 posted by hand, 1 real) led to four
emailed reports in 10 to 16 s with 19 audited read-only tool calls and 18 model calls (17,924 prompt and 1,207
completion tokens, USD 0.0034). Web fallback on 14 questions, twice: never triggered for the 8 corpus-answerable
asks; unanswerable ones refused every time; but with default settings it triggered on 1 of 10 corpus-miss questions
(0 of 6 answerable from the allowlisted pages). With the refusal gate raised to 0.72: 1 of 6 triggered and grounded,
4 of 6 grounded answers counting stored copies.

**Tests.** No new unit tests. Evidence: `eval/reports/pq1-2-3-live-triage-fallback-2026-11-18.md` and two answers
files `eval/reports/pq1-2-3-fallback-answers-gate050.jsonl`, `...-gate072.jsonl`. Runner:
`scripts/pq123_web_fallback_run.py`.

**How to run.** Start the `agent` and `monitoring` profiles with the chat provider set on the `api` service (the base
compose file does not pass it), web fallback on with an allowlisted host and entry URLs, then post alerts to
`/alerts` with the webhook token and run the script with `EKA_RUN_KEY` set to a user key. Needs the OpenAI key in the
environment and approved spend. Mail goes to Mailpit.

**Expected.** One mail per alert; audit lines `tool=... call=N`; the script prints one line per question with
fallback and refusal flags.

**Failure modes.** The fallback trigger is the best of the top 5 dense cosines below 0.50, which off-topic questions
usually pass on a small corpus. After the first fetch, weak questions are not redirected to the stored pages inside the
refresh window. The agent keeps no token counts, so a counting proxy was used. Three reports had a wrong or guessed
cause because the edge was not in the stack.

**Talking points.** State the rubric before the run; report the miss (fallback hit rate near zero by default) with the
cause found in the cosines; keep the tuned-gate run labelled as tuned on the same questions.

## F17 Deploy step and alarm queue on LocalStack (PQ1.2.5)

**What it proves.** Without an AWS account: the `jq` filter that `.github/workflows/deploy.yml` uses replaces the image
tags and drops registration-only fields (4 good fixtures) and rejects 3 bad inputs; the alarm path (SNS topic, queue,
dead-letter queue with redrive after 5 receives, a test alarm) works on LocalStack, and the real triage agent jar
reads an alarm from the queue and sends one email to Mailpit. `terraform destroy` leaves nothing behind.

**Tests.** `scripts/test_deploy_jq.sh` (fixtures in `scripts/deploy_fixtures/`) and `scripts/queue_localstack_drill.sh`
(uses `infra/aws/localstack/` and `scripts/fake_openai.py`). Evidence:
`eval/reports/pq1-2-5-localstack-2026-11-19.md` (7 of 7 jq cases; drill ALL PASSED).

**How to run.** Docker running; `bash scripts/test_deploy_jq.sh`, then `bash scripts/queue_localstack_drill.sh` (about 3
minutes). Run one drill at a time.

**Failure modes.** Leftover stopped `pq125-*` containers (the script now removes them); Git Bash path conversion for
Docker (`MSYS_NO_PATHCONV=1`); two drills at once share containers and Terraform state.

**Honest limits.** The model is scripted, so this proves wiring, not triage quality. The real
`aws ecs register-task-definition`, the deploy and real alarm evaluation timing need an AWS account and were not run.

## F18 Admin key and digest consistency

**What it proves.** Prometheus scrapes with the plain admin key in `monitoring/secrets/admin_key`, while the core holds
only its SHA-256 digest in the admin entry of `EKA_API_KEYS` in `.env`. Both were set by hand, so they drifted (found
in PQ1.2.3: Prometheus got 401). `eka.tools.sync_admin_key` checks and repairs this and never prints the key or digests.

**Tests.** `tests/test_sync_admin_key.py` (mismatch then sync then match; rotate; missing files give exit 2; output
contains neither key nor digest).

**How to run.** `pytest tests/test_sync_admin_key.py`. On a machine: `python -m eka.tools.sync_admin_key --check`
(prints `match` or `mismatch`), `--sync` (file wins), `--rotate` (new key and digest).

**Failure modes.** More than one admin entry in `EKA_API_KEYS` makes `--sync` refuse (exit 2). Restart `api` after a
change to `.env` so the core reads the new digest.

## F19 Edge interop fixtures (stale token files)

Status: root cause found and fixed in the test procedure on 2026-11-19; no product bug. Local, free.

| Check | Setup | Result |
|---|---|---|
| Tokens minted by the real edge verify in the core | `tests/test_edge_interop.py` (3 tests: user token accepted, admin token accepted, wrong audience refused) reads `gateway/target/interop/*.jwt` and `jwks.json`, written by `InteropFixtureTest` in the edge test run | accepted and refused as designed when the fixtures are fresh |
| Failure seen | full `pytest` on 2026-11-18 with the fixture files older than the one-hour leeway the test allows | 2 failed, including `test_edge_user_token_is_accepted` (F1 failure modes): expired token, not a defect in the edge or core |
| Fix | `cd gateway && mvn -o -q -B test` rewrites the fixtures (offline, quiet, batch); deleting `gateway/target/interop` makes the module skip instead | 2026-11-19: with regenerated fixtures the full `pytest -q` with Docker up gave 691 passed, 5 skipped; without Docker `pytest -m "not integration"` gave 612 passed, 5 skipped, 79 deselected |

**Why it was built this way.** The edge's internal token lives 60 seconds by design. The interop test needs a token that was really minted by the Java edge, so it reads a file the edge test wrote and relaxes only expiry (leeway 3600 s). That makes the test depend on file age, which is a known weakness, not a fault in the token rules (ADR-022, `PLATFORM_FACTS.md` section 2).

**Trade-offs and alternatives.**

- Regenerating the fixture before the Python run keeps the real cross-language proof. Minting a fresh token inside the Python test would need the edge's private key, which the core must never have.
- A much longer leeway would hide the symptom but weaken what the test shows about expiry; it was not changed.
- Skipping when the folder is absent keeps clean checkouts green, but a stale folder fails instead of skipping. Making the test also skip on stale files is a possible change and was not made.

**Not covered / limits of this evidence.** The 5 skipped tests: two are the opt-in real-embedding tests (`EKA_TEST_REAL_MODEL`); the other three are to be confirmed. The fixture run needs Maven and Java 21 locally.

**Pending.** How CI orders the edge job and the Python job with respect to this fixture: to be confirmed after the next push.

## F20 Edge rate limit, shared Redis limiter and the 40-parallel burst

Status: limiter built 2026-11-13 (P13); burst measured 2026-11-19 as part of the platform INT-4 run (local, free). Evidence: platform register E-63; reconcile-ai `docs/proof/int-4-concurrency-2026-11-19.md`.

| Check | Setup | Result |
|---|---|---|
| Shared limit across edge instances | `RedisRateLimiterTest` (4 tests, real Redis in `gateway/src/test/java/com/eka/edge/ratelimit/`); `RateLimitTest` (2) for the in-memory limiter | two edge instances allowed 5 of 10 requests together, where in-memory counting allows 10 (README, P13); the limiter fails open if Redis is down |
| 40 parallel searches at the real edge | platform INT-4 stack, one user, default limits (burst 20, 5 per second, in memory) | 21 x 200 and 19 x 429; every 429 has `Retry-After: 1` and a `problem+json` body (`urn:eka:problem:rate-limited`) with no query text |
| 60 parallel searches | same | 21 x 200 and 39 x 429 |
| reconcile-ai calling EKA under load | 25 parallel investigations, wide pool, fail-open | 2 of 25 lookups got 429; reconcile-ai recorded `UNAVAILABLE / RATE_LIMITED` (the `RATE_LIMITED` handling), continued without procedures and all 25 jobs SUCCEEDED |
| Same, fail-closed | `KNOWLEDGE_FAIL_CLOSED=true` | 3 jobs failed retryably with `KNOWLEDGE_UNAVAILABLE` (2 rate limited, 1 timeout), no model call; re-run 3 of 3 succeeded |
| EKA core not answering | core paused during 10 investigations | 10 of 10 lookups `TIMEOUT` at the 5 s limit, then the caller's breaker opened (`CIRCUIT_OPEN`, no request sent) |

**Why it was built this way.** A per-user token bucket at the edge protects the core from one noisy caller before any retrieval work starts (ADR-025). The shared Redis variant exists because two edge tasks counting separately would double the limit. Knowledge is advisory for reconcile-ai, so a limited lookup degrades to "no procedures" instead of failing the investigation.

**Trade-offs and alternatives.**

- 21 allowed in a 40-request burst is the bucket (20) plus one refill: the shape of the limiter, not a recommended limit.
- In-memory counting is simplest and has no dependency, but it is per instance; Redis shares it at the price of one more component that must fail open.
- A retry with backoff on `Retry-After: 1` inside reconcile-ai is a possible later change; it was not added because it is a design choice, not a defect.

**Not covered / limits of this evidence.** One laptop, one run each, one user identity, one edge instance, stub model upstream of EKA, at most 60 parallel requests: behaviour figures, not capacity. Log scan of the EKA edge, core and worker containers found 0 payload or secret hits, but the edge log was read as the Docker tail (1000 lines).

**Pending.** Two edge instances behind the shared Redis limiter under the INT-4 load (to be confirmed; not in the proof); real-AWS ElastiCache run (never applied).

## F21 EKA identity in the platform login test (INT-3) and the admin key

Status: done locally 2026-11-19 (platform E-60, 27 of 27 checks across services); the admin key tool is F18.

| Check | Setup | Result |
|---|---|---|
| Platform token with `aud=eka-api` at the edge | platform `scripts/int/int3.sh`, EKA edge on port 8480 (`--profile edge`, audience `eka-api`) | `GET /me` 200 |
| Tokens for other audiences at the edge | tokens for `ai-gateway`, `ops-agent`, and console | 401 |
| No token | same | 401 |
| Tenant mapping | tenant-a and tenant-b service tokens | two different owner ids (`user_id` differs); the edge derives the id from `iss` plus `sub`, never from a tenant claim |
| Roles | token roles claim | EKA reads no roles for these tokens (admin only if `eka-admin` is present) |

**Why it was built this way.** EKA has no tenant concept; isolation is per owner (`PLATFORM_FACTS.md` section 3). A machine client therefore needs its own identity per tenant, and the pseudonym keeps the provider's `sub` out of the database. The check that two tenant clients map to different owners is the identity half of the isolation proof (E-26 shows the document half).

**Trade-offs and alternatives.** One identity per tenant is simple and works for a few demo tenants; it does not scale to many (token exchange or a tenant-aware mapping would). Calling the core directly with an API key would skip the edge's checks and is for local use only.

**Not covered / limits of this evidence.** Identity only: no document work in this run. Keycloak is `start-dev`.

**Pending.** Hosted identity provider beside Keycloak (D1.2.6, needs a real account).

## F22 AWS deployment code (Terraform for ECS) and what has not run

Status: written and validated; never applied. CI job `terraform` runs `terraform fmt -check -recursive` and `terraform validate`. The LocalStack alarm-queue drill is F17.

| Check | Setup | Result |
|---|---|---|
| Format and validation | CI job `terraform` (Terraform 1.13.0, `init -backend=false`) | passes (README) |
| ECS Fargate | `infra/aws/ecs.tf`: edge and core in one task (talk over `localhost`), a worker service, a one-off migration task | validate only |
| Added in P13 | `autoscaling.tf` (api 2 to 4 tasks), `cache.tf` (ElastiCache with TLS), `waf.tf`, `deploy_role.tf` (GitHub OIDC), `alarms.tf` | validate only; "code only, not applied" |
| Triage agent on AWS (P14) | `ops_agent.tf`: own Fargate service, no inbound port, alarms through SNS and SQS | tested with a stand-in SQS client and, since 2026-11-19, a LocalStack drill (F17); real alarm timing not run |
| Deploy step | `scripts/test_deploy_jq.sh` | 7 of 7 cases (F17) |

**Why it was built this way.** The point was to have reviewed, validated infrastructure code and honest labels on it, without spending money or claiming a deployment.

**Trade-offs and alternatives.** Edge and core in one task remove a network hop and keep the core private, at the price of scaling them together. Validating only is free; a real apply would catch service limits, Bedrock model access and the pgvector version RDS offers, which `infra/aws/README.md` lists as unverified.

**Not covered / limits of this evidence.** Never planned or applied against an account. In the platform integration, EKA expects an existing `vpc_id`; the integration is not applyable as-is (platform AWS guide: shared-VPC root and ops-agent Terraform missing).

**Pending.** Real apply, record and destroy (needs credentials and cost approval); WAF and deploy role in a real account.

## F23 Copyright and canary headers, view-only policy

Status: done 2026-11-19 on branch `chore/headers-canary` (commit `c8121ac`; the branch is pushed and its tracking state is up to date). Merge and CI run id: to be confirmed.

| Check | Setup | Result |
|---|---|---|
| Policy and notice | `AI_USE_POLICY.md` and the README section "License and AI use" (commit `8020fb0`, merged by PR #1) | all rights reserved; training, AI analysis or reproduction, dataset inclusion and scraping need written permission |
| Header on source files | `git grep` for the canary marker | 269 tracked files carry it: 267 source files (169 `.py`, 73 `.java`, 25 `.ts`) plus README and the policy |
| Deliberate exclusion | `eval/corpus/RetryPolicy.java` | no header: it is evaluation data and evaluation questions (for example q43, q44) cite its text |
| Build still works | not re-run after the change in this docs pass | to be confirmed (the Python files only gained comment lines; reconcile-ai and ai-gateway UI builds were verified in E-58) |

Header form: a copyright line, an SPDX identifier `LicenseRef-Proprietary` with "View only; see LICENSE and AI_USE_POLICY.md", and the canary line (marker value is in the README and policy, not repeated here).

**Why it was built this way.** The repo is public to be read; the notice states in every file that reading is the permitted use. The marker lets the owner detect a copy.

**Trade-offs and alternatives.** Headers add three lines to each file and can be stripped; the policy is a legal notice, not a technical control. Excluding the eval corpus file keeps the evaluation corpus text unchanged, so earlier retrieval results stay comparable.

**Not covered / limits of this evidence.** A view-only proprietary `LICENSE` file, which the headers refer to, appeared in the working tree on 2026-11-19 (about 17:00) and is untracked (uncommitted); commit and CI: to be confirmed. No search for copies was done.

**Pending.** Merge of the branch and commit of `LICENSE`; owner decision on a hybrid public-portfolio setup.

## F24 Test counts, lint and types (2026-11-19)

| Check | Setup | Result |
|---|---|---|
| Core tests, default | `pytest -m "not integration"` | 612 passed, 5 skipped, 79 deselected (696 collected) |
| Full suite with Docker | `pytest -q` with Docker up, fixtures regenerated (F19) | 691 passed, 5 skipped |
| Ruff | `ruff check .`, `ruff format --check .` | clean; 184 files formatted |
| Mypy strict | `mypy src tests` | clean; 161 files typed (`mypy src scripts`: 93 files) |
| Admin key tool | `tests/test_sync_admin_key.py` | 3 tests (F18) |
| Edge | `cd gateway && mvn -B verify` | 47 tests in the last recorded CI run 43393823859; later local count: to be confirmed |

Values are taken from the README "Test evidence" table written on 2026-11-19 and were not re-run in this docs pass (the default set could not run here because pytest is not installed in the shell Python). Earlier full run: 616 passed, 5 skipped, coverage 91.1% (gate 85%), 2026-11-11.

## F25 Link following, local log shipping to CloudWatch and the browser test (P16, 2026-11-13)

| Check | Setup | Result |
|---|---|---|
| Link following in web fallback (ADR-039, off by default) | `tests/test_web_links.py`, 8 unit tests (BRD AC-29); live run against docs.python.org | one level, same host and directory, robots.txt respected, capped per entry page; live run stored an entry page and 5 linked pages and answered citing a linked page |
| Local log shipping to CloudWatch (ADR-040, profile `cloudwatch`) | Vector and LocalStack 4.9; the triage agent searches the group | core log lines appear in the group `eka/core/<id>` and are found with and without an `ERROR` filter (BRD AC-30); never run on real AWS |
| Browser test in CI (ADR-041) | `ui/e2e/smoke.spec.ts` (Playwright), CI job `ui-browser` | 6 local passes in a row on 2026-11-13; CI job green in run 44296520354 (2026-11-18) |

**Why it was built this way.** Link following lets a documentation question reach the next page without a general crawler; the one-level, same-directory rule and robots.txt keep it narrow and safe. Shipping logs to CloudWatch locally tests the AWS log path without an account. The browser test catches what unit tests cannot (a login bug was found that way).

**Trade-offs and alternatives.** A search engine or deep crawl would find more pages and widen the attack surface (SSRF, injection); it was rejected. LocalStack is a stand-in, so real CloudWatch behaviour is unproven.

**Not covered / limits of this evidence.** Web fallback checked with the fake chat model except for the live questions in F16; real CloudWatch and real Bedrock never called.

**Pending.** Real AWS runs.
