# Enterprise Knowledge Assistant (EKA)

[![CI](https://github.com/YellaiahMekala/Enterprise-Knowledge-Assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/YellaiahMekala/Enterprise-Knowledge-Assistant/actions/workflows/ci.yml)

**Core stack**  
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white) ![Java 21](https://img.shields.io/badge/Java-21-ED8B00?logo=openjdk&logoColor=white) ![AI and RAG](https://img.shields.io/badge/AI-RAG-7B2CBF) ![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white) ![Spring Boot](https://img.shields.io/badge/Spring_Boot-Edge-6DB33F?logo=springboot&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white) ![pgvector](https://img.shields.io/badge/pgvector-0.8.7-4169E1) ![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white) ![pytest](https://img.shields.io/badge/pytest-testing-0A9EDC?logo=pytest&logoColor=white) ![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-CI-2088FF?logo=githubactions&logoColor=white)

Chat with your documents through a REST API. Each answer cites the document, page and passage it came from, and the service declines to answer when the retrieved evidence is weak.

> **Notice: independent demonstration project.**
> This is a generic, fictitious application built to demonstrate software engineering skills. It does not
> contain, reflect or derive from any client's or employer's data, code, functionality, architecture, designs
> or confidential information, and it is not affiliated with or endorsed by any current or former employer or
> client. All data is synthetic, and any resemblance to real people, organisations or documents is
> coincidental. Credentials in this repository are development-only. It is provided "as is", without warranty,
> and is not intended for production use without independent security review and hardening.

Architecture: Angular web UI → Spring Boot edge (Java 21: OIDC token validation, credential swap to a short-lived internal token, rate limit, audit, SSE passthrough) → FastAPI RAG core → PostgreSQL with pgvector. The core also runs on its own with API-key authentication. The sections below say what has been checked and what has not.

## Status

Everything below was run locally between 2026-11-07 and 2026-11-09 against the Docker Compose stack
(PostgreSQL 17 with pgvector, core, worker, edge, Prometheus, Alertmanager, Grafana, Keycloak, the
triage agent) on a development laptop. All GitHub Actions jobs pass on `main`: core lint, types and
tests (Python 3.11 and 3.12), integration with the coverage gate, image build, edge, UI, API
contract, evaluation, monitoring, ops-agent and Terraform validate. The first run of the edge job
failed on a timing problem in the test fixture (a hung fake core stalled later tests); the fix is in
the history.

### Built and checked

| Area | What exists | How it was checked |
|---|---|---|
| Core API (FastAPI) | Typed settings that refuse a half-configured start, problem+json errors with a request id, liveness and readiness probes | 522 tests pass, 8 skipped, 91.7% coverage (gate 85%) |
| Authentication | API-key mode (SHA-256 digests, constant-time compare) and gateway mode (ES256 internal token from the edge, key set fetched from the edge) | Unit tests; a token minted by the real edge verifies in the core; behind the edge the core answers 401 to an identity-provider token, an API key and no credential |
| Isolation | Owner-scoped repositories plus row-level security that fails closed; leakage tests through search | Integration tests; two users through the edge see only their own documents |
| Ingestion | Upload (PDF, DOCX, CSV, code, text) validated by content, background worker, local BGE-small embeddings | 13 mixed files ingested through the Docker stack |
| Retrieval | Dense (pgvector HNSW) and full-text candidates fused by reciprocal rank; metadata filters; refusal gate on cosine similarity | Tests; evaluation below |
| Chat | Cited answers over JSON or server-sent events; verified mode (default) and fast mode; conversation memory; OpenAI-compatible adapter | Run with the fake model only: a cited answer, a `weak_evidence` refusal, both stream modes. No live model was used |
| Edge (Spring Cloud Gateway, Java 21) | OIDC token validation, credential swap to a 60-second internal token, per-user rate limit, audit log, SSE passthrough with client-disconnect cancel, problem+json for upstream failures, circuit breaker on the core route (fast 503 `circuit-open` while open), Prometheus on a private port | 43 tests (hung-core drill, breaker opens after repeated timeouts and its state is exported, streaming spike); through the real image: bad tokens 401, role mapping, tokens spaced about 100 ms apart, 12 of 45 rapid requests limited |
| Observability | Admin-only `/api/v1/admin/metrics`, request counts and latency by route template; Prometheus and Grafana as an opt-in Compose profile; SLO recording rules and 4 alerts as code, each linked to a runbook | Prometheus scraped core and edge; the dashboard loaded in Grafana; `promtool test rules` passes 4 alert test cases |
| Operations | [Runbooks](docs/runbooks.md) per alert, SLOs with error budget, database backup and restore scripts, restore drill | Restore drill passed: migration version, row counts and row-level security identical after restore (8 s, local data) |
| Web UI (Angular) | Sign-in by API key, document status, streamed chat with citations, conversation list | 11 unit tests; a scripted browser run (sign-in failure and success, documents, verified and fast chat, refusal, sign-out) passed 10 times in a row |
| Identity provider | Keycloak realm in Compose (`--profile idp`) with two test users and an `eka-admin` role | 7 end-to-end checks through the real edge (`scripts/keycloak_e2e.sh`): no or bad token 401, user 200, admin route 403 for a user and 200 for the admin, role claim mapped |
| File storage | Local disk (default) or S3 / any S3-compatible server (`EKA_STORAGE_BACKEND=s3`), chosen in one place | 9 tests against an in-process fake S3, and 2 against a real S3-compatible server in a container |
| Reranking (experiment E3) | Optional cross-encoder over the top 20 candidates, off by default ([ADR-032](docs/adr/ADR-032-optional-cross-encoder-reranking.md)) | Evaluation: Hit@1 95.5% to 100%, MRR 0.977 to 1.000 (2 of 44 questions); about 560 ms extra per query on a laptop CPU |
| Incident triage agent (LangChain4j, Java 21) | Receives Alertmanager webhooks, investigates with 3 read-only tools (PromQL query, service health, runbook), emails a report; token-protected, call budget, audit log, runbook-only fallback ([ADR-033](docs/adr/ADR-033-incident-triage-agent.md)) | 41 tests including the full tool loop with a scripted model; drills against the real stack: a synthetic alert and a real one (core stopped, Prometheus fired `EkaTargetDown`, email in about 4 minutes) both arrived in a local mail catcher. Not run with a live model or real SMTP |
| Amazon Bedrock chat provider | `EKA_CHAT_PROVIDER=bedrock` through the Converse API, credentials from the AWS chain, no key in settings ([ADR-034](docs/adr/ADR-034-bedrock-provider-and-aws-deployment.md)) | 10 tests against a stub client: request shape, streaming, early close, error mapping. Never called Bedrock |
| AWS deployment (Terraform, `infra/aws`) | ECS Fargate (edge and core in one task, worker, migration task), RDS PostgreSQL 17, S3, Secrets Manager, load balancer, task role limited to the bucket and Bedrock | `terraform validate` and `fmt` pass (also in CI). Never planned or applied against an account |
| API contract | Postman collection | 36 assertions, 0 failures against the Compose stack |

### Load, local run (10 users for 20 s, fake chat model, 13 documents)

| Endpoint | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|
| `POST /api/v1/search` | 58 req/s | 163 ms | 231 ms | 305 ms | 0 |
| `POST /api/v1/chat` | 35 req/s | 282 ms | 358 ms | 410 ms | 0 |

These are one laptop and a fake model, so a real model's latency would dominate chat. They show the harness works and the service stays error-free under that load; they are not capacity claims.

### Measured

Retrieval on a 44-question set over 13 short documents (one chunk each), BGE-small, 256-token chunks, run locally:

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

I read the 8 string-match misses, the refusal and the wrong citation. I did not read the other 36 answers, so the 43 of 44 figure is not a full hand score. Token counts are not returned by the API and were not recorded. One run, one model, questions written by the author: a sanity check, not a benchmark.

Triage agent with `gpt-4o-mini`, one synthetic `EkaHighErrorRate` alert, mail to the local catcher: the agent made 3 read-only calls (runbook, service health, one PromQL query) and sent a report in about 11 s. The core and edge were not running in that test, so the tools correctly reported them unreachable; the report's guess of "database issues" was the model's own and wrong (the database was up), which is why the report says to check the evidence before acting. One run; real email delivery was not tested.

### Not done

| Item | Note |
|---|---|
| Query-prefix experiment (E5) | Not run |
| Reranking on by default | Needs a larger evaluation set than 13 chunks (see ADR-032) |
| Two live-answer defects | q31 is wrongly refused and q29 cites the wrong file; causes not yet investigated |
| Full hand scoring of live answers | Only the misses were read (see above) |
| Other models | Only `gpt-4o-mini` was run |
| Entra ID or other hosted identity provider | Tested against Keycloak only |
| UI sign-in through the identity provider | The UI still signs in with an API key |
| Real email delivery | Verified only into a local mail catcher; real SMTP not tried |
| Alert delivery redundancy | If the agent is down there is no second path to email |
| Log search for the agent | There is no log store |
| Allowlisted web fallback (ADR-030) | Not built; off by design |
| Real Bedrock call, real AWS deployment | Needs an AWS account; the code is written and unit-tested or validated only |

## Tech stack

Built so far: Python 3.11+, FastAPI, Pydantic, SQLAlchemy 2 (async) over psycopg 3, Alembic, PostgreSQL with pgvector, pytest, Testcontainers, Ruff, mypy, Docker, GitHub Actions (written).

Chosen in the design, not yet built: local BGE-small embeddings through fastembed, an OpenAI-compatible chat model behind an interface, `pypdf` and `python-docx` parsers, a Java 21 Spring Boot edge service with OIDC and an internal signed token to the core, an Angular web UI, and local-disk or S3 file storage. There is no orchestration framework in the first version; LangChain is admitted only if a specific need appears ([ADR-002](docs/adr/ADR-002-no-orchestration-framework.md)).

## Documentation

| Document | Contents |
|---|---|
| [Business requirements](docs/BRD.md) | Business outcomes, scope, functional and non-functional requirements with status, acceptance criteria, risks |
| [Decision records](docs/adr/README.md) | One file per architecture decision with options, cost, risk and review trigger |
| [Runbooks](docs/runbooks.md) | SLOs, one runbook per alert, backup and restore procedure |
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
(cd ui && npx ng test --watch=false && npx ng build)
scripts/restore_drill.sh          # backup, restore to scratch, compare (stack running)
```

Alert rules: `promtool test rules monitoring/alerts.test.yml` (CI runs it in the `prom/prometheus` image).

If you change the API on purpose, regenerate the snapshot with `python -m eka.tools.export_openapi` and review the diff.

## Docker

```bash
docker compose up --build        # database and API
curl http://localhost:8000/health/ready
```

Compose needs the settings from `.env` (it refuses to start without `EKA_DB_PASSWORD` and `EKA_API_KEYS`). The image runs as a non-root user, writes JSON logs and defaults to `EKA_ENVIRONMENT=prod`, which hides the API docs; Compose sets `local` so `/docs` stays available. Compose does not apply migrations yet (a one-shot migrate service arrives with ingestion): run `alembic upgrade head` once against the database. The database port is published on `127.0.0.1` only, for local use.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `EKA_ENVIRONMENT` | `local` (`prod` in the image) | `local`, `test` or `prod`; `prod` hides `/docs`, `/redoc` and `/openapi.json`. Outside `test` the settings below are required and startup fails without them |
| `EKA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `EKA_LOG_JSON` | `false` (`true` in the image) | One JSON object per log line |
| `EKA_DATABASE_URL` | none (required) | `postgresql+psycopg://user:password@host:port/database`; treated as a secret |
| `EKA_AUTH_MODE` | none (required) | `api_key` (`gateway` is rejected until the Java edge exists) |
| `EKA_API_KEYS` | none (required in `api_key` mode) | JSON object: `{"<user-id>": {"sha256": "<64 hex characters>", "role": "user"}}` with role `user` or `admin` |
| `EKA_DB_PASSWORD`, `EKA_DB_PORT` | none (required), `5432` | Used by `docker-compose.yml` for the database service |

Settings come from environment variables or a git-ignored `.env` file (copy `.env.example`). Secrets are supplied the same way and never committed.

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health/live` | none | The process is up |
| GET | `/health/ready` | none | Ready for traffic: the database answers (503 otherwise); returns the build version |
| GET | `/api/v1/me` | key | The caller's user id and role |
| GET, POST, DELETE | `/api/v1/documents`, `/api/v1/documents/{id}` | key | Upload, list, inspect, delete |
| POST | `/api/v1/search` | key | Hybrid retrieval with filters |
| POST | `/api/v1/chat` | key | Cited answer as JSON, or as a stream with `"stream": true` |
| GET, DELETE | `/api/v1/conversations`, `/api/v1/conversations/{id}` | key | Conversation history |
| GET | `/api/v1/admin/status`, `/api/v1/admin/metrics` | admin key | Build info; Prometheus metrics |

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
  security/           API-key authentication
  api/                routers, dependencies, the problem+json handler
  adapters/db/        engine and row-level-security session, table models, repositories
  tools/              hash_key, export_openapi, loadtest
ops-agent/            incident triage agent (Java 21, LangChain4j): webhook, read-only tools, report email
keycloak/             test realm for the identity provider profile
scripts/              database backup, restore, restore drill, Keycloak end-to-end check
alembic/              migrations (roles, tables, indexes, row-level security)
docs/openapi.json     committed API contract
tests/                offline tests; tests/integration needs Docker
```

## Web UI

An Angular app in `ui/` with sign-in by API key, document upload and status, and chat with streamed
answers and citations.

```bash
docker compose up -d          # core on :8000
cd ui && npm ci && npm start  # http://localhost:4200, /api proxied to :8000
```

Tests: `npm test`. The API key stays in `sessionStorage` for the tab only.

## Postman collection

`postman/eka.postman_collection.json` checks authentication, authorization, the error format and the
metrics endpoint, plus search, chat and documents when a database is available. The key variables
in `postman/local.postman_environment.json` are empty; pass them with `--env-var` or fill them in
Postman. CI runs the database-free folders against a core started in test mode.
