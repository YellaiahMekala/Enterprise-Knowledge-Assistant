# Business Requirements Document (BRD): Enterprise Knowledge Assistant (EKA)

| | |
|---|---|
| Version | 0.3 (draft for approval) |
| Date | 2026-10-31 |
| Status of the product | Core, edge, UI, evaluation and operations basics built (phases P0 to P7, 2026-11-07); CI runs on GitHub Actions. Everything marked Planned below is design, not code. |
| Related documents | Architecture · Technical Design (TDD) · Implementation Plan · Test Strategy · Threat Model · Operational Readiness · Release Evidence · [Decision records](adr/README.md) |

**Status vocabulary.** *Done* = built and verified by a run. *Partial* = some of it exists, with the gap stated. *Planned* = designed, not built. Nothing in this document describes planned work as built.

| Revision | Date | Change |
|---|---|---|
| 0.1 | 2026-10-31 | First draft: RAG core, Angular UI, Java gateway as design only |
| 0.2 | 2026-10-31 | After external assessment: Java edge service becomes a delivered slice (FR-60 to FR-67); business outcomes, stakeholders and data classification added; operability, threat model, resilience and release-evidence requirements added (NFR-14 to NFR-18); phases renumbered (edge is P5); decisions moved to `adr/` |
| 0.3 | 2026-10-31 | After an external review and owner decisions: code and text corpus (FR-36); optional allowlisted web fallback, Planned (FR-37); verified and fast answer modes (FR-38); evaluation challenge set (FR-51); decisions D-1, D-2, D-5 and D-6 recorded; AC-21 to AC-23; risks R15 and R16; R5, R8 and R14 updated |

---

## 1. Purpose

EKA lets people upload their own documents (PDF, DOCX, CSV) and ask questions about them in natural language. Every answer cites the document, the page (or section, or rows) and the exact passage it came from, and the service declines to answer when the retrieved evidence is weak. Each user sees only their own documents.

It is a reference implementation of a production-shaped retrieval-augmented generation (RAG) system: a Python RAG core behind a Java 21 / Spring Boot enterprise edge that owns identity, authorization, audit, rate limits and resilience, with a web UI on top. It is not a hosted product.

## 2. Problem statement

| # | Problem | Consequence |
|---|---|---|
| P1 | Answers live inside long policy and procedure documents; keyword search misses paraphrases | People read whole documents or ask colleagues |
| P2 | General chat assistants answer from memory and do not cite | Plausible but unverifiable (and sometimes wrong) answers |
| P3 | A shared index mixes everyone's documents | One user's content can surface in another user's answer |
| P4 | Most RAG demos have no measurement | Nobody can say whether a change to chunking or ranking helped |
| P5 | Demos skip operations: identity, limits, audit, cost, failure handling, recovery | They cannot be run, defended in a security review, or supported |

## 3. Business outcomes and objectives

### 3.1 Target enterprise use case
Internal policy and procedure Q&A for a regulated organisation (for example HR, compliance and operations manuals). Employees ask in natural language and get an answer with the exact page to verify. Compliance needs an audit trail, no cross-user exposure and control over what leaves the organisation. Platform teams need a service they can monitor, limit and recover.

**Secondary use case (owner's Java full-stack tutor corpus).** The owner's private Java learning material (PDFs, code and notes) is ingested as a static corpus and queried for answers with file and line or page citations. Where the corpus cannot answer, an optional fallback may consult an allowlist of official documentation sites (FR-37, Planned). The corpus is private and never committed; public demos use a synthetic or openly licensed corpus.

### 3.2 Value hypotheses
These are **hypotheses, not findings.** No real users have been involved.

| ID | Hypothesis | How it can be tested here | What would count against it |
|---|---|---|---|
| H1 | Citing the exact page lowers the effort to verify an answer | Only by a user pilot (out of scope). This project measures proxies: citation validity and locator accuracy | A pilot showing no time saved |
| H2 | Refusing weak-evidence questions lowers the share of unsupported answers | Refusal recall and false-refusal rate on the evaluation set | False-refusal rate above target (O3) at any threshold with recall at target |
| H3 | An enterprise edge in front of a model service lets identity, limits and audit evolve without redeploying the model service | Restart or replace the edge alone in Compose while the core keeps running; contract tests on both sides | Edge changes forcing core changes |

Decision criteria fixed before measuring: if Hit@5 on paraphrase questions stays under 0.6 after experiments E1 to E3, the retrieval design is reworked before more features are built.

### 3.3 Objectives and success measures

| ID | Objective | Measure | Target (set before measuring; revise only with evidence) |
|---|---|---|---|
| O1 | Answers are traceable | Share of non-refused answers with at least one valid citation | 100% (enforced by the server, FR-31) |
| O2 | Retrieval finds the right passage | Hit@5 and MRR on the evaluation set | Hit@5 ≥ 0.85 (to be measured in P6) |
| O3 | The service says "I don't know" correctly | Refusal recall on unanswerable questions; false-refusal rate on answerable ones | Recall ≥ 0.90; false refusals ≤ 0.10 (to be measured in P6) |
| O4 | No cross-user leakage | Leakage probes in the evaluation and test suites | 0 leaked chunks, 0 leaked citations |
| O5 | Changes are measurable | Evaluation runs in CI and fails on regression | Gate active from P6 |
| O6 | Runnable by anyone | `docker compose up` brings up the whole stack | Verified in P9 |
| O7 | Identity is enforced before data is reached | AC-12, AC-13, AC-15 and AC-16 pass: invalid tokens rejected at the edge, core unreachable directly, limits and audit enforced | All pass in CI (P5) |
| O8 | The system is operable | SLOs defined with alerts as code; resilience scenarios, load profile and a restore drill executed and recorded | Evidence rows in Release Evidence (P7, P9) |

Measured values are recorded in the README results table only after they are produced by a real run and logged in the evidence ledger. None have been produced yet.

### 3.4 Non-goals
Not a general chatbot (answers come only from the user's documents) · not a document management system (no folders, versions, sharing) · not a search engine over the web · not a compliance product (it supports audit; it is not certified) · not multi-language · no autonomous actions (the model has no tools).

## 4. Users and stakeholders

### 4.1 Personas

| Persona | Needs | Notes |
|---|---|---|
| End user | Upload documents; ask questions; see exactly where each answer came from; trust that others cannot see their files | Primary |
| Administrator | See usage (requests, tokens, latency, refusals) and document statuses across users | Sees metadata only, never other users' content or conversations |
| Maintainer | Change chunking, models or prompts and know from numbers whether quality moved; operate the stack | Uses the evaluation harness, dashboards and runbooks |

### 4.2 Stakeholder roles
Roles used to drive and review requirements. **No real stakeholders have been consulted; this is a design exercise.**

| Role | Concern | Satisfied by |
|---|---|---|
| Policy owner | Answers match the document and can be verified | FR-31, O1, O2 |
| Employee | Fast, trustworthy answers; privacy of own documents | FR-33, FR-02, O4 |
| Information security and compliance | Identity, audit, data egress, least privilege | FR-60 to FR-66, data classification (4.3), Threat Model |
| Platform and operations | Monitoring, limits, rollback, recovery | NFR-14, NFR-15, NFR-17, Operational Readiness |
| Finance | Cost per question is bounded and visible | NFR-05, FR-50, FR-62 |
| Engineering maintainers | Replaceable parts, tests, honest status | NFR-08, NFR-09, NFR-18, Test Strategy |

### 4.3 Data classification
Uploaded document text is sent to the chat provider as retrieved passages (risk R2). The permitted use follows the classification of the documents.

| Class | Examples | With a hosted chat provider in v1 | Control |
|---|---|---|---|
| Public | Published manuals | Allowed | None needed |
| Internal | Internal policies and procedures | Allowed if the provider's terms allow it | Upload notice in the UI |
| Confidential | Unreleased policies, contracts | Only with a provider agreement that permits it | Upload acknowledgement; procedural |
| Restricted | Personal data, payment-card data, health data, credentials | **Not allowed** with a hosted provider | Needs the local-model adapter (Planned). **No automated detection in v1**: the control is procedural, and this is a stated residual risk |

## 5. Scope

### In scope
Ingestion of PDF, DOCX, CSV and code or text files (`.java`, `.md`, `.txt`, `.xml`, `.sql` and similar); cleaning, chunking with overlap and metadata; embeddings and hybrid search with metadata filters; cited, streamed answers with refusal; conversation memory; per-user isolation; **a Java 21 / Spring Boot edge service** (OIDC resource server, role authorization, rate limits, audit, resilience, SSE passthrough, tracing); Angular web UI with OIDC sign-in; admin usage view; local-disk and S3 storage; Docker, CI and an evaluation set that CI runs; SLOs, alerts as code, runbooks, a threat model and a release-evidence ledger.

### Out of scope (v1)
Scanned-image PDFs and OCR · languages other than English · sharing documents between users or organisation-level access control · SAML and enterprise identity-provider integration beyond a standards-compliant OIDC resource server · agents and tool calling · fine-tuning · billing · Kubernetes manifests · file types other than PDF, DOCX, CSV and code or text files; Kafka, MCP, multi-agent workflows and a second vector database · production traffic and production-measured SLOs · multi-replica distributed rate limiting (Proposed).

### Assumptions
1. Documents are text-based, English, and at most 20 MB / 500 pages each (configurable).
2. Identity comes from an OIDC identity provider. A development provider runs in Compose; a real one is configuration (issuer and JWKS).
3. An OpenAI-compatible chat endpoint and API key are needed only for live answer generation; development starts with a fake chat provider (decision D-5), and live checks are reported as not run until a key is set. Embeddings run locally and need no key.
4. A user's corpus stays under roughly 50,000 chunks; the sizing in Architecture §8 covers 100 such users.
5. Sending retrieved passages to the chat provider is acceptable to the document owner for classes Public and Internal (4.3).
6. One maintainer builds and operates the system; role hats (backend, platform, security, SRE, frontend) are used to structure review, not to claim a team.

## 6. Functional requirements

Priority: **M** must · **S** should · **C** could. Phase refers to the Implementation Plan.

### 6.1 Identity and isolation (core)
| ID | Requirement | Pri | Status | Phase |
|---|---|---|---|---|
| FR-01 | The core authenticates every request except health probes: in standalone mode by `X-API-Key` mapped to a user id and role (digests, constant-time compare); in edge mode by a valid internal token from the edge only. Otherwise 401 | M | Done: API-key mode (P1) and edge mode, which accepts only the edge's ES256 internal token (P5); tested both ways | P1, P3b, P5 |
| FR-02 | A user can list, read, search, ask about and delete only their own documents and conversations. Another user's resource id returns 404 (not 403) | M | Done: owner-scoped repositories and row-level security on every table; leakage tests through search, answers and conversations; two users through the edge see only their own data | P1–P4 |
| FR-03 | An administrator can read usage and document metadata for all users but not document text, passages or conversations | S | Partial: admin status and metrics endpoints and an admin read policy on document metadata; per-user usage report Planned | P7 |

### 6.2 Ingestion
| ID | Requirement | Pri | Status | Phase |
|---|---|---|---|---|
| FR-10 | Upload PDF, DOCX or CSV as multipart; validate real file type (content, not only extension), size and per-user quota; store the raw file; respond 202 with document id and status | M | Done | P2 |
| FR-11 | Upload is idempotent: the same content (SHA-256) from the same user returns the existing document and creates no duplicate chunks | S | Done | P2 |
| FR-12 | Extract text with a locator: PDF → page number; DOCX → heading path; CSV → row range (header row kept with each chunk) | M | Done | P2 |
| FR-13 | Clean text: Unicode normalisation, control-character removal, de-hyphenation across line breaks, whitespace collapse | M | Done | P2 |
| FR-14 | Chunk with configurable size and overlap, measured in the embedding model's tokens and never above its input limit. A chunk never crosses a page, section or row-group boundary | M | Done | P2 |
| FR-15 | Tag each chunk with metadata: document id, file name, owner, locator, ordinal, character offsets, content type, upload time, embedding model, chunking configuration | M | Done | P2 |
| FR-16 | Embed chunks and index them for dense and full-text search; set the document to `ready`. On failure set `failed` with a safe error code and retry up to a configured limit | M | Done | P2 |
| FR-17 | List (paged), inspect status of, and delete documents. Delete removes rows, vectors and the raw file | M | Done | P2 |
| FR-18 | Reject unsupported, corrupt, password-protected and image-only files with a specific error code | S | Done | P2 |
| FR-19 | Store raw files through a storage interface with a local-disk adapter (default) and an S3 adapter selected by configuration | S | Done: local-disk and S3 adapters (any S3-compatible server), selected by configuration; tested against a fake S3 and a real S3-compatible server. Not tried on AWS | P2 (local done), P9 (S3 Planned) |

### 6.3 Retrieval
| ID | Requirement | Pri | Status | Phase |
|---|---|---|---|---|
| FR-20 | Hybrid retrieval: dense vector search and full-text search fused by reciprocal rank fusion (RRF), always filtered by owner, with optional filters (document ids, content type, upload date range) | M | Done | P3 |
| FR-21 | A search endpoint returns ranked chunks with scores and locators (used by the UI, the evaluation harness and Postman) | M | Done | P3 |
| FR-22 | Optional cross-encoder reranking of the top candidates, switched by configuration and enabled by default only if the evaluation shows a gain | C | Done: optional cross-encoder reranking, off by default; measured in experiment E3 (ADR-032) | P6 |

### 6.4 Answers
| ID | Requirement | Pri | Status | Phase |
|---|---|---|---|---|
| FR-30 | Answer using only retrieved passages; passages are presented to the model as untrusted data | M | Done | P4 |
| FR-31 | Attach citations (document, page/section/rows, exact passage). Citation references are checked against the retrieved set; the passage text comes from the stored chunk, never from the model. An answer left with no valid citation is recorded as a refusal (`no_valid_citation`) | M | Done (checked with the fake model; no live model run) | P4 |
| FR-32 | Refuse when evidence is weak: below a calibrated retrieval threshold the LLM is not called; the model may also declare insufficient evidence. A refusal says why | M | Done: cosine gate before the model and the model's insufficient-evidence reply; threshold from the evaluation sweep | P4, P6 |
| FR-33 | Stream answers over Server-Sent Events (retrieval, token, done, error events); a non-streaming JSON mode also exists. Client disconnect cancels the provider call | M | Done | P4 |
| FR-34 | Persist conversations; rewrite follow-up questions into standalone queries using a bounded window of recent turns | M | Done | P4 |
| FR-35 | Create, list, read and delete conversations | S | Done | P4 |

### 6.5 Interface
| ID | Requirement | Pri | Status | Phase |
|---|---|---|---|---|
| FR-40 | Angular web UI: sign in with OIDC (authorization code with PKCE) through the edge; upload with live status; document list and delete; chat with streamed answers; clickable citations that show the passage; conversation list | M | Partial: UI built with API-key sign-in, document status, streamed chat, citations and conversations; OIDC sign-in and upload from the UI Planned | P8 |
| FR-41 | Admin view: requests, tokens, latency and refusals by user and day; document counts by status | S | Partial: admin API built; admin view in the UI Planned | P7 (API), P8 (view) |

### 6.6 Quality and operations (core)
| ID | Requirement | Pri | Status | Phase |
|---|---|---|---|---|
| FR-50 | Record a usage event per question (tokens, models, latency, retrieval count, refused flag). No question or answer text in usage events | S | Partial: one usage event per question (mode, model, latency, retrieval count, refused flag, prompt and completion size in characters); token counts Planned | P7 |
| FR-51 | Evaluation harness: versioned corpus and question set plus a separate challenge set (long documents, table-heavy PDFs, exact identifiers, conflicting documents, cross-tenant probes, injection attempts, code questions); retrieval and refusal metrics; a hand-scored answer-quality sample against a written rubric (model judging supplementary); Markdown report; CI regression gate | M | Partial: harness, corpus, question and challenge sets, report and CI gate built; hand-scored answer quality needs a live model and was not run | P3, P6 |
| FR-52 | Health probes: `/health/live` and `/health/ready`; readiness also reflects database and embedding-model availability | M | Partial: liveness and database-aware readiness built (503 when the database is down); embedding-model availability Planned | P1, P2 |

FR-52 status: both endpoints exist and are tested; readiness currently checks nothing beyond the process (it has no dependencies yet).

### 6.7 Enterprise edge (Spring Boot, Java 21)
| ID | Requirement | Pri | Status | Phase |
|---|---|---|---|---|
| FR-60 | The edge authenticates every external request as an OAuth2 resource server: signature via JWKS, issuer, audience, expiry and an algorithm allow-list. Failure returns 401 and the request never reaches the core | M | Done | P3b, P5 |
| FR-61 | The edge mints a short-lived (≤ 60 s) internal token (asymmetric signature; subject, role, request id, unique id) for each forwarded request; the core in edge mode accepts only such tokens, and is not reachable from outside the private network | M | Done | P3b, P5 |
| FR-62 | Per-user rate limits, a per-user concurrent-stream limit and an edge request-size limit; violations return 429 with `Retry-After` and never reach the core | S | Partial: per-user token-bucket rate limit with 429 and Retry-After; concurrent-stream limit and quotas Planned | P5 |
| FR-63 | Audit trail: sensitive actions (authentication failures, upload, delete, admin routes) are recorded durably **before** forwarding and refused if the audit store is unavailable; other requests are recorded best-effort. Records contain ids and outcomes, never document or question text | S | Partial: one audit line per forwarded request (pseudonym, role, method, path, request id) on a separate logger; durable audit store Planned | P5 |
| FR-64 | Resilience: timeouts, circuit breaker on the core, bulkhead on streams, retries only for idempotent GETs. SSE passes through unbuffered and client disconnect cancels the upstream call. Failures return problem+json (503, 504) | M | Partial: timeouts, problem+json for upstream failures and a circuit breaker on the core route built and tested; bulkhead Planned | P5 |
| FR-65 | W3C trace context and a request id flow from the edge through the core into logs and audit records; edge and core expose metrics | S | Partial: request id flows from the edge to the core and into logs; W3C trace context and traces Planned | P5, P7 |
| FR-66 | Route authorization by role claim at the edge (admin routes require the admin role) | M | Partial: the edge maps the role claim into the internal token and the core enforces admin routes (403); route-level rules at the edge Planned | P5 |
| FR-67 | API lifecycle: versioned routes (`/api/v1`), deprecation signalling for future versions, and committed contract snapshots checked in CI for the edge's external and internal contracts | C | Partial: routes versioned under `/api/v1`; deprecation signals Planned | P5 |

### 6.8 Learning corpus, answer modes and web fallback

| ID | Requirement | Pri | Status | Phase |
|---|---|---|---|---|
| FR-36 | Ingest code and text files (`.java`, `.md`, `.txt`, `.xml`, `.sql` and similar allow-listed extensions): UTF-8 only, size-capped, binary rejected; chunk preferring class and method boundaries; locator is file plus line range | S | Done | P2 |
| FR-37 | Optional web fallback: when the user's documents give weak evidence, fetch from an owner-configured allowlist of official HTTPS sites only (SSRF-safe, size and time capped, redirects re-checked), treat the page as untrusted, store it as a document with source URL and fetch date, and cite it as a web source distinct from document citations | C | Planned (optional) | P4b |
| FR-38 | Two answer-streaming modes: **verified** (default) releases text only after citations validate; **fast** (optional) streams immediately, marks text provisional, and the final event confirms or replaces it | M | Done | P4 |

## 7. Non-functional requirements

All numeric targets are **targets, not measurements**. They are verified in P6, P7 and P9, and the results are recorded in the Release Evidence ledger and the README.

| ID | Category | Requirement | Status |
|---|---|---|---|
| NFR-01 | Security | Deny by default; secrets only from environment or secret store; keys stored as digests and compared in constant time; no secrets in logs, errors or responses; asymmetric signing keys for internal tokens | Done: deny by default, secrets from environment only, key digests with constant-time compare, internal tokens signed by the edge |
| NFR-02 | Isolation | Owner predicate enforced in the data-access layer on every query, with database row-level security as a second layer; verified by automated leakage tests | Done: both layers built; leakage tests across search, answers and conversations on a real PostgreSQL |
| NFR-03 | Latency | Retrieval-only request p95 ≤ 500 ms for a user with 50,000 chunks; time to first streamed token p95 ≤ 3 s through the edge, excluding provider outages; edge overhead p95 ≤ 20 ms (see Architecture §9) | Planned (target): not measured at 50,000 chunks; a 13-document load run gave search p95 231 ms (README) |
| NFR-04 | Ingestion | A 100-page text PDF reaches `ready` in ≤ 2 minutes on 2 vCPU | Planned (target) |
| NFR-05 | Cost | Bounded prompt: top-k, context-token and output-token caps; per-question token accounting; per-user limits at the edge; embeddings at zero marginal cost | Partial: top-k, context and output caps, per-question usage events and per-user rate limits built; token accounting Planned |
| NFR-06 | Reliability | Timeouts and bounded retries with backoff on provider calls; interrupted ingestion resumes after restart; failures return typed errors, never partial fabricated answers | Partial: provider timeouts and bounded retries; the worker reclaims stale jobs after a crash; edge timeouts and circuit breaker. Fault injection beyond the edge Planned |
| NFR-07 | Observability | JSON logs with request and trace ids; Prometheus metrics from edge and core; distributed traces; usage events | Partial: JSON logs with request id, Prometheus metrics from edge and core, Grafana dashboard, usage events; distributed traces Planned |
| NFR-08 | Testability | Offline test suites for both services; one real-database integration layer; evaluation set in CI; contract tests across the edge-core boundary | Done: core 489 tests (integration on a real PostgreSQL), edge 43, UI 11, evaluation gate and API-contract run in CI |
| NFR-09 | Portability | LLM, embedder, reranker and file storage sit behind interfaces so providers are replaceable by configuration | Done: chat model, embedder, reranker and file storage sit behind interfaces; each has at least two adapters or a fake |
| NFR-10 | Maintainability | Ruff and mypy strict clean; line coverage gate ≥ 85% in CI; Java build with architecture tests | Done: ruff and strict mypy clean; the 85% coverage gate passes in CI; edge architecture tests |
| NFR-11 | Delivery | Non-root multi-stage images for core, edge and UI; one-command local stack; CI on every push | Partial: non-root multi-stage core and edge images, one-command Compose stack, CI on every push; UI image Planned |
| NFR-12 | Data lifecycle | Deleting a document leaves no retrievable trace of its content (search and question paths); retention and deletion rules documented | Partial: document delete built and tested; retention policy Planned |
| NFR-13 | Accessibility | UI is keyboard operable with labelled controls | Partial: labelled controls and keyboard submit in the UI; not audited |
| NFR-14 | SLOs and error budgets | SLIs, SLOs, a 30-day error budget and burn-rate alerts defined; alert rules and dashboards stored as files, validated in CI. SLOs are objectives for the reference deployment, not production measurements | Partial: SLOs, a 30-day error budget, burn-rate and latency alerts as code, `promtool` unit tests in CI; a live error-burst drill Planned |
| NFR-15 | Operational readiness | Runbook per alert, incident triage guide, rollback procedure, backup and restore procedure with a restore drill, key rotation procedure | Partial: runbook per alert, first-checks triage, backup and restore scripts, restore drill passed (same cluster), alert-to-email path drilled with a real alert and an incident triage agent (ADR-033); restore into a clean environment with measured RPO/RTO Planned |
| NFR-16 | Threat model | Threat model maintained with every threat mapped to a control and a test group; residual risks listed | Partial: drafted in Threat Model; test evidence Planned |
| NFR-17 | Resilience | Specified behaviour for provider outage, database loss, worker crash and edge-to-core failure, verified by fault-injection tests; recovery targets RPO ≤ 24 h and RTO ≤ 1 h for the reference deployment (targets) | Partial: edge-to-core failure verified (timeout 504, breaker 503); provider outage, database loss and worker crash drills Planned |
| NFR-18 | Evidence | Every claim in README, docs, deck or posts maps to a row in the evidence ledger (CI run, report or test result) | Partial: ledger structure drafted; rows Planned |

## 8. Acceptance criteria

| ID | Verifies | Criterion |
|---|---|---|
| AC-01 | FR-02, O4 | User A uploads a document; user B searches and asks questions that match it. B receives zero chunks, zero citations and a 404 for A's document id. |
| AC-02 | FR-32 | For a question absent from the corpus, the response has `refused: true` and a reason, and the fake LLM records zero calls. |
| AC-03 | FR-31 | Every non-refused answer has at least one citation; each citation's passage is a substring of the stored chunk and its locator equals the chunk's locator; references outside the retrieved set are dropped. |
| AC-04 | FR-11 | Uploading the same bytes twice as one user yields one document and one set of chunks. |
| AC-05 | FR-10, FR-18 | A `.exe` renamed `.pdf` → 415; a file over the limit → 413; a password-protected PDF → document `failed` with code `encrypted`. |
| AC-06 | FR-33 | A streamed answer emits `retrieval`, then at least one `token`, then `done`. Closing the connection cancels the provider call. |
| AC-07 | FR-51, O5 | The evaluation command prints the metrics table; CI fails when Hit@5 falls more than the configured margin below the committed baseline. |
| AC-08 | FR-17, NFR-12 | After delete, the document's rows, vectors and raw file are gone and no search returns its text. |
| AC-09 | FR-34 | For a follow-up such as "and for contractors?", the query sent to retrieval contains the topic from the previous turn (asserted with a fake LLM). |
| AC-10 | NFR-01 | Starting outside `test` with no authentication configured fails at startup with a clear message. |
| AC-11 | FR-52 | `/health/ready` returns 503 when the database is unreachable. |
| AC-12 | FR-60, O7 | The edge returns 401 for tokens that are expired, signed with another key, issued for another audience or issuer, unsigned (`alg: none`), or using an algorithm outside the allow-list; the upstream records zero calls. |
| AC-13 | FR-61 | In edge mode the core returns 401 to a request without a valid internal token, and no core port is published by the edge-mode Compose file. An internal token older than its lifetime is rejected. |
| AC-14 | FR-64, FR-33 | Through the edge, the first SSE event reaches the client before the upstream response completes; closing the client connection cancels the upstream stream within the configured grace period. |
| AC-15 | FR-62 | With a limit of N requests per window, request N+1 returns 429 with `Retry-After`, and the core received exactly N. |
| AC-16 | FR-63 | Each sensitive action produces exactly one audit record with request id and no text; with the audit store down, sensitive actions return 503 and do not reach the core. |
| AC-17 | FR-64, NFR-17 | After the configured number of upstream failures the circuit opens and the edge answers 503 immediately; it closes again after the core recovers. |
| AC-18 | NFR-14 | Alert rule files pass `promtool check rules`, and a synthetic error burst in the reference stack fires the fast-burn alert. |
| AC-19 | NFR-15, NFR-17 | A backup is restored into a clean environment and the smoke test and evaluation pass; measured RPO and RTO are recorded. |
| AC-20 | NFR-18 | Each claim listed in the README maps to a row in the evidence ledger with a date and a link or file. |
| AC-21 | FR-36 | A `.java` file and a Markdown file reach `ready`; a chunk never splits inside a method when the method fits the budget; the citation locator is file plus line range; a binary file renamed `.java` is rejected. |
| AC-22 | FR-38 | In verified mode a response with an invalid citation never sends the invalid text to the client; in fast mode the text is marked provisional until `done`, and a failed validation replaces it with a refusal. |
| AC-23 | FR-37 | Planned. Requests to hosts outside the allowlist, to private or link-local addresses, and redirects leaving the allowlist are refused; a web answer carries a web citation with URL and fetch date. |

## 9. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Approximate vector search with a filter can return fewer than k rows (pgvector HNSW applies the filter after the index scan) | High | Medium | Iterative index scan, `ef_search` sizing, exact scan for small per-user sets; skewed multi-user test (TDD §4.6) |
| R2 | Document text leaves the deployment when sent to a hosted chat model | Certain (by design) | High for sensitive data | Data classification (4.3); chat provider is an interface; local-model adapter Planned; no document text in logs, usage events or audit records |
| R3 | Evaluation set is small, so metrics are noisy (n ≈ 50 gives roughly ±10 points) | High | Medium | Report counts and confidence intervals; treat differences under the margin as noise; grow the set |
| R4 | DOCX has no fixed pages, so "page" cannot be exact | Certain | Low | Typed locator (ADR-007) |
| R5 | Streaming can send text before citations are validated | Medium | Medium | Verified mode (default) buffers until validation; fast mode is optional, labels text provisional, and the final event confirms or replaces it ([ADR-031](adr/ADR-031-verified-and-fast-streaming-modes.md)) |
| R6 | Prompt injection through uploaded documents | Medium | Medium | Passages treated as data; no tools; server-side citation and refusal checks; adversarial document in the corpus; Threat Model |
| R7 | Embedding model change invalidates stored vectors | Low | Medium | Model name stored per chunk; re-embed job (ADR-005) |
| R8 | Schedule: the plan was 15 days for the core; adding the edge and operability work makes the total about 24 working days nominal (range 21.5 to 36) for one engineer, excluding the optional web fallback | High | High | Milestone plan with confidence ratings, spikes, release criteria per milestone and an explicit cut line (Implementation Plan) |
| R9 | The edge slice grows into a platform | Medium | Medium | Hard boundaries in ADR-021: no retrieval logic, one route family, audit schema only |
| R10 | Identity-provider setup consumes time or hides defects | Medium | Medium | Spike S-4; development identity provider isolated to a Compose profile; token-validation tests use generated keys, not the provider |
| R11 | Two languages and two pipelines double build and review effort | High | Medium | Shared contract snapshots; one Compose stack; CI jobs per module; architecture tests in both |
| R12 | Fail-closed auditing makes sensitive actions unavailable when the audit store is down | Medium | Medium | Deliberate trade-off (ADR-024); store health alert; non-sensitive traffic unaffected |
| R13 | Restricted-class data uploaded by mistake and sent to a hosted provider | Medium | High | Procedural control only in v1 (4.3); upload acknowledgement; local-model adapter Planned |
| R14 | Spring Boot 3.5.x line is at or past the end of public releases (last release on Maven Central dated 2026-06-25), so the edge uses 4.1.x | Medium | Medium | Decided (D-1): Spring Boot 4.1.x with Spring Cloud 2025.1.x, confirmed by a dependency spike in P3b (ADR-021) |
| R15 | The web fallback opens a new attack surface (SSRF, prompt injection from fetched pages, allowlist bypass through redirects) | Medium | High | Optional and Planned; allowlist-only, address checks after DNS resolution, redirect re-checks, size and time caps, content treated as untrusted ([ADR-030](adr/ADR-030-allowlisted-web-fallback.md), Threat Model) |
| R16 | The owner's private learning material (possibly copyrighted) is committed or published by mistake | Low | High | Corpus lives in a git-ignored `data/` folder; secret and file-list review before every commit; public demos use a synthetic or openly licensed corpus |

## 10. Dependencies

PostgreSQL with the pgvector extension · an OpenAI-compatible chat API and key · the BGE embedding model files (downloaded on first use or baked into the image) · an OIDC identity provider (development provider in Compose) · JDK 21 and Maven for the edge · optionally an S3-compatible object store.

## 11. Approval

| Gate | Condition | State |
|---|---|---|
| BRD | Owner approves scope, including the edge slice and the revised effort | Pending |
| TDD | Every FR maps to a component (TDD §1) | Drafted; pending approval |
| Threat model | Every threat has a control and a planned test group | Drafted; pending approval |
