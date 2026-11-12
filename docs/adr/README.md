# Architecture decision records

One file per decision. Status values: **Accepted** (confirmed in design review), **Proposed** (recommended, awaiting approval), **Superseded** (kept as a record). The decision owner is the single maintainer; review triggers say when to revisit rather than leaving decisions open-ended.

Template: Status, Date, Decision owner, Review trigger, Related requirements or decisions; then Context, Decision, Options considered (with cost and risk), Consequences.

| ID | Decision | Status |
|---|---|---|
| [ADR-001](ADR-001-python-core-java-edge.md) | Python core for model-side work, Java edge for enterprise concerns | Accepted (amended by ADR-021) |
| [ADR-002](ADR-002-no-orchestration-framework.md) | No orchestration framework in v1; LangChain only if required | Accepted |
| [ADR-003](ADR-003-postgresql-pgvector-single-store.md) | PostgreSQL with pgvector as the only core datastore | Accepted |
| [ADR-004](ADR-004-hybrid-retrieval-rrf.md) | Hybrid retrieval with reciprocal rank fusion | Proposed |
| [ADR-005](ADR-005-local-bge-embeddings.md) | Local BGE-small embeddings through fastembed | Accepted |
| [ADR-006](ADR-006-chat-model-port.md) | Chat model behind a port; OpenAI-compatible default | Accepted |
| [ADR-007](ADR-007-page-bounded-chunks-typed-locator.md) | Page-bounded chunks and a typed locator | Proposed |
| [ADR-008](ADR-008-server-side-citations.md) | Citations resolved and validated on the server | Proposed |
| [ADR-009](ADR-009-refusal-gate.md) | Refusal gate before the model, on a calibrated signal | Proposed |
| [ADR-010](ADR-010-db-backed-ingestion-queue.md) | Database-backed ingestion queue with a separate worker | Proposed |
| [ADR-011](ADR-011-api-key-and-gateway-hmac.md) | API key now, signed gateway headers later (original decision) | Superseded by ADR-022 |
| [ADR-012](ADR-012-isolation-repository-contract-rls.md) | Isolation by repository contract plus row-level security | Proposed |
| [ADR-013](ADR-013-storage-port.md) | Storage port with local disk and S3 adapters | Accepted |
| [ADR-014](ADR-014-sse-over-post-fetch.md) | Streaming over POST with fetch, not EventSource | Proposed |
| [ADR-015](ADR-015-angular-nginx-same-origin.md) | Angular frontend served by nginx on the same origin | Accepted (amended by ADR-022 and on 2026-11-11) |
| [ADR-016](ADR-016-problem-json-errors.md) | RFC 9457 problem+json for all errors | Proposed |
| [ADR-017](ADR-017-plain-parsers.md) | Plain parsers, not Unstructured or LlamaParse | Proposed |
| [ADR-018](ADR-018-retrieval-eval-in-ci.md) | Retrieval evaluation in CI; model-judged evaluation manual | Proposed |
| [ADR-019](ADR-019-code-first-contract-snapshot.md) | Code-first contracts with committed snapshots in CI | Proposed (extended in v0.2) |
| [ADR-020](ADR-020-sqlalchemy-async-psycopg.md) | SQLAlchemy 2 (async) over psycopg 3, with Alembic | Proposed |
| [ADR-021](ADR-021-java-edge-vertical-slice.md) | Spring Boot edge service delivered as a vertical slice | Proposed |
| [ADR-022](ADR-022-oidc-edge-identity-internal-jwt.md) | Standards-based edge identity: OIDC resource server and internal JWT | Proposed |
| [ADR-023](ADR-023-gateway-runtime-spring-cloud-gateway.md) | Gateway runtime: Spring Cloud Gateway (WebFlux), subject to a spike | Proposed |
| [ADR-024](ADR-024-edge-audit-design.md) | Edge audit trail: fail-closed for sensitive actions, best-effort otherwise | Proposed |
| [ADR-025](ADR-025-edge-rate-limits-and-quotas.md) | Edge rate limits and concurrency quotas, in-memory in v1 | Proposed |
| [ADR-026](ADR-026-edge-resilience-policy.md) | Edge resilience policy: timeouts, circuit breaker, bulkhead, no blind retries | Proposed |
| [ADR-027](ADR-027-observability-otel-micrometer.md) | Observability with OpenTelemetry trace context and Prometheus metrics | Proposed |
| [ADR-028](ADR-028-slo-error-budget-alerts-as-code.md) | SLOs, error budgets and alerts as code | Proposed |
| [ADR-029](ADR-029-code-aware-chunking.md) | Code and text loaders with code-aware chunking and a line-range locator | Proposed |
| [ADR-030](ADR-030-allowlisted-web-fallback.md) | Allowlisted web fallback for official documentation (optional, off by default) | Accepted |
| [ADR-031](ADR-031-verified-and-fast-streaming-modes.md) | Verified (default) and fast streaming modes | Proposed |
| [ADR-032](ADR-032-optional-cross-encoder-reranking.md) | Optional cross-encoder reranking, off by default | Accepted |
| [ADR-033](ADR-033-incident-triage-agent.md) | Incident triage agent as a separate service | Accepted |
| [ADR-034](ADR-034-bedrock-provider-and-aws-deployment.md) | Bedrock chat provider and an AWS deployment shape | Accepted |
| [ADR-035](ADR-035-log-search-loki.md) | Log search for the triage agent with Loki and Alloy | Accepted |
| [ADR-036](ADR-036-citation-grounding-and-refusal-gate.md) | Citation grounding check and a refusal gate of 0.50 | Accepted |
| [ADR-037](ADR-037-token-cost-and-ttft-accounting.md) | Token, cost and time-to-first-token accounting | Proposed |
| [ADR-038](ADR-038-model-fallback-chain-and-breaker.md) | Model fallback chain with a per-model circuit breaker | Proposed |
