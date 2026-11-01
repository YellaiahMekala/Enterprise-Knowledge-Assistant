# Enterprise Knowledge Assistant (EKA)

Chat with your documents through a REST API. Each answer will cite the document, page and passage it came from, and the service will decline to answer when the retrieved evidence is weak.

> **Status: foundation.** The service skeleton, API-key authentication, the PostgreSQL schema with row-level isolation, and the delivery files exist and have been checked by local runs. The retrieval-augmented generation (RAG) features, the enterprise edge and the web UI are designed (see Documentation) and not built yet. Nothing in this repository has been measured for retrieval quality, latency or load, and the CI workflow has not run yet.

Planned architecture (not built): Angular web UI → Spring Boot enterprise edge (Java 21, Spring Boot 4.1: OIDC token validation, audit, rate limits, resilience) → FastAPI RAG core → PostgreSQL with pgvector. A thin version of the edge is built right after isolated search, so the Java layer is exercised by every later phase.

## Built, measured and planned

The tables below follow the [evidence ledger](docs/Release_Evidence.md): a claim appears under Built or Measured only when the ledger has a row for it.

### Built (checked by local runs on 2026-10-31; no CI run exists yet)

| Item | Evidence |
|---|---|
| FastAPI app factory, typed and validated settings (`EKA_*`) that refuse a half-configured start, text or JSON logs, liveness and database-aware readiness probes | Tests; run against the Compose database (ledger E-008, E-011) |
| API-key authentication: keys held as SHA-256 digests, constant-time comparison over every entry, deny by default; `GET /api/v1/me` is 401 without a valid key and 200 with one | Tests, including a route walk that fails if a new route needs no key; live run (C-07) |
| One error format (RFC 9457 problem+json) with a request id; internal detail is logged, never returned | Tests |
| PostgreSQL 17 with pgvector 0.8.7: `documents` and `chunks` tables, HNSW and full-text indexes, applied by reversible Alembic migrations | Integration tests on a real database; migration run (E-009, E-010) |
| Per-user isolation in two layers: an owner-scoped repository, and row-level security that fails closed (a session without an owner sees nothing) | 11 row-level-security tests on a real database; the tests were checked by weakening the policy and watching them fail (C-08, E-013) |
| Import-boundary and repository-signature tests that enforce the layering; committed OpenAPI snapshot that fails the build when the contract changes | Tests (C-09) |
| Docker image (multi-stage, non-root, health check) and Compose stack (database and API) | Built and run locally; readiness is 503 with the database stopped and recovers after restart (C-06, E-012) |
| Lint, format and strict type checks clean; 123 tests; 94.16% line coverage (gate 85%) | Ruff, mypy and `pytest --cov` runs (E-007, E-008) |

### Written, not yet verified

| Item | What is missing |
|---|---|
| GitHub Actions workflow (lint and types on Python 3.11 and 3.12, offline tests, integration tests with the coverage gate, image build and smoke test) | The workflow has not been run on GitHub. Its steps were run by hand locally |

### Measured

Nothing yet. Retrieval hit rate, refusal behaviour, latency and resilience results will be listed here only after a recorded run.

### Planned (by milestone)

| Milestone | Outcome |
|---|---|
| M1 | PDF, DOCX, CSV and code or text ingestion with page, section, row or line locators; hybrid retrieval with metadata filters; per-user isolation with leakage tests through search |
| M1.5 | Thin Java edge: OIDC token validation, `GET /api/v1/me`, internal token to a private core, one end-to-end contract test |
| M2 | Streamed answers that cite document, page and passage, and decline when evidence is weak; verified (default) and fast streaming modes; conversation memory; developed first against a fake chat model |
| M3 | Complete Spring Boot edge: role authorization, audit, rate limits, circuit breaking, SSE passthrough |
| M4 | Evaluation set and a separate challenge set run in CI with a regression gate; hand-scored answer sample; results table (retrieval hit rate and refusal behaviour) |
| M5 | SLOs and alerts as code, runbooks, fault-injection and load results, restore drill |
| M6 | Angular UI through the edge, complete CI, Postman collection, demo |
| Optional | Allowlisted web fallback for official documentation sites (disabled by default; built only after M2 and only if approved) |

## Tech stack

Built so far: Python 3.11+, FastAPI, Pydantic, SQLAlchemy 2 (async) over psycopg 3, Alembic, PostgreSQL with pgvector, pytest, Testcontainers, Ruff, mypy, Docker, GitHub Actions (written).

Chosen in the design, not yet built: local BGE-small embeddings through fastembed, an OpenAI-compatible chat model behind an interface, `pypdf` and `python-docx` parsers, a Java 21 Spring Boot edge service with OIDC and an internal signed token to the core, an Angular web UI, and local-disk or S3 file storage. There is no orchestration framework in the first version; LangChain is admitted only if a specific need appears ([ADR-002](docs/adr/ADR-002-no-orchestration-framework.md)).

## Documentation

| Document | Contents |
|---|---|
| [Business requirements](docs/BRD.md) | Business outcomes, stakeholders, data classification, scope, functional and non-functional requirements with status, acceptance criteria, risks |
| [Architecture](docs/Architecture.md) | Principles, constraints, fitness functions, review record, containers, security zones, capacity, latency, SLOs and error budgets |
| [Technical design](docs/TDD.md) | Core and edge components, data model, API and internal contracts, sequences, security, configuration, failure modes |
| [Decision records](docs/adr/README.md) | One file per architecture decision with options, cost, risk and review trigger |
| [Threat model](docs/Threat_Model.md) | Data flows, trust boundaries, STRIDE and LLM threats, controls, test mapping, residual risks |
| [Operational readiness](docs/Operational_Readiness.md) | Alerts and runbooks, incident triage, release and rollback, backup and restore, retention, key rotation, drills |
| [Implementation plan](docs/Implementation_Plan.md) | Milestones with estimates, confidence and release criteria; spikes; cut line; open decisions |
| [Test strategy](docs/Test_Strategy.md) | Test layers, security, resilience and recovery tests, edge tests, retrieval evaluation, CI design, known gaps |
| [Release evidence](docs/Release_Evidence.md) | Ledger tying every public claim to recorded evidence |
| [OpenAPI snapshot](docs/openapi.json) | The committed API contract; a test fails if the code and this file differ |

These documents describe the target system. The tables above and the status columns in each document show what is built.

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
pytest -m "not integration"      # 95 offline tests, no Docker needed
pytest --cov=eka --cov-fail-under=85   # everything; the 28 integration tests start a throwaway PostgreSQL and skip if Docker is off
```

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
| GET | `/api/v1/me` | `X-API-Key` | The caller's user id and role, taken from the key |

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
  tools/              hash_key, export_openapi
alembic/              migrations (roles, tables, indexes, row-level security)
docs/openapi.json     committed API contract
tests/                offline tests; tests/integration needs Docker
```
