# Platform facts (from code, 2026-11-13, commit 1e81215)

Every fact gives the file it was read from. UNVERIFIED means it could not be confirmed in code.
Paths: `core/` = `src/eka/`, `edge/` = `gateway/src/main/java/com/eka/edge/`.

## 1. Endpoints (core)

Errors from the core use one shape, RFC 9457 `application/problem+json` (`core/api/errors.py` `problem()`):
`{type: "urn:eka:problem:<slug>", title, status, detail, instance, request_id}` plus extras below.
The `X-Request-ID` response header carries the same id (`core/api/errors.py`).

| Status | slug | Extra fields | Source |
|---|---|---|---|
| 401 | `unauthorized` (header `WWW-Authenticate: ApiKey`, detail "A valid API key is required." in both auth modes) | | `core/api/errors.py` |
| 403 | `forbidden` (not admin) / `quota-exceeded` (document quota) | | `core/api/errors.py` |
| 404 | `not-found` (also another user's id) | | `core/api/errors.py`, `core/api/documents.py` docstring |
| 413 | `payload-too-large` | | `core/api/errors.py` |
| 415 | `unsupported-media-type` | `reason` (fixed code, e.g. `type_mismatch`) | `core/api/errors.py` |
| 422 | `validation` | `errors: [{loc, msg, type}]` (input not echoed) | `core/api/errors.py` |
| 400 | `bad-request` (admin usage window) | | `core/api/admin.py`, `core/api/errors.py` |
| 502 | `model-unavailable` | | `core/api/errors.py` |
| 503 | `unavailable` (database or a dependency) | | `core/api/errors.py` |
| 504 | `model-timeout` | | `core/api/errors.py` |
| 500 | `internal` | | `core/api/errors.py` |

Refusals are **not** errors: `POST /chat` returns 200 with `refused: true` and `refusal_reason` one of
`weak_evidence` (best cosine below `EKA_REFUSAL_MIN_COSINE`, model not called), `no_passages`, `model_declined`
(model replied `INSUFFICIENT_EVIDENCE`), `unverified_citations` (`core/domain/answering.py`, `core/services/answering.py`).
Refusal text: "I could not find this in your documents." (`core/domain/answering.py`).

| Method | Path | Roles | Request | Response | Notes |
|---|---|---|---|---|---|
| GET | `/health/live` | none | | | `core/api/health.py` |
| GET | `/health/ready` | none | | 503 when not ready | `core/api/health.py` |
| GET | `/api/v1/me` | user, admin | | `{user_id, role}` | `core/api/me.py`. Behind the edge, the edge answers this path itself (`edge/web/MeController.java`) |
| POST | `/api/v1/documents` | user, admin | multipart `file` (required). Max `EKA_MAX_UPLOAD_MB` (default 20); PDF, DOCX, CSV, or extensions in `EKA_ALLOWED_TEXT_EXTENSIONS` (default `.java .md .txt .xml .sql .properties .yml .json`, each ≤ `EKA_MAX_TEXT_FILE_KB` 512) | `DocumentOut` | **202** + `Location: /api/v1/documents/{id}` for a new file; **200** with the existing document when the same bytes were uploaded before (idempotent by content). 403 quota (`EKA_MAX_DOCS_PER_USER` 200), 413, 415. `core/api/documents.py`, `core/config.py` |
| GET | `/api/v1/documents` | user, admin | query `status` (pending/processing/ready/failed), `limit` 1–100 (50), `offset` ≥0 | `{items: [DocumentOut], limit, offset}` newest first | `core/api/documents.py` |
| GET | `/api/v1/documents/{id}` | user, admin | path UUID | `DocumentOut` | **Polling path** for ingestion. 404 if not the caller's. `core/api/documents.py` |
| DELETE | `/api/v1/documents/{id}` | user, admin | | 204 | deletes chunks and stored file. `core/api/documents.py` |
| POST | `/api/v1/search` | user, admin | `query` str 1–1000 chars (req); `top_k` int 1–20 (5); `filters{document_ids: UUID[] ≤200, content_types: str[] ≤10, uploaded_after, uploaded_before: datetime}` | `{query, results: [{rank, chunk_id, document_id, filename, locator, text, scores{fused, cosine, rerank}}]}` | Synchronous. Owner-scoped. `scores.rerank` is **always null**: `SearchResultOut.from_hit` never sets it, even with a reranker on. `core/api/search.py`, `core/services/retrieval.py` (`MAX_QUERY_CHARS = 1000`) |
| POST | `/api/v1/chat` | user, admin | `question` str 1–1000 (req); `conversation_id` UUID; `top_k` 1–10 (5); `mode` `verified`/`fast`; `stream` bool (false) | JSON `{conversation_id, message_id, answer, citations[{index, chunk_id, document_id, filename, locator, quote, kind: document/web, source_url, fetched_at}], refused, refusal_reason, mode, verified, web_fallback}`; or SSE events `meta`, `token{text, provisional}`, `replace{text}`, `done`, `error{status, type, detail}`, heartbeat `:` every 15 s | `core/api/chat.py` |
| GET | `/api/v1/conversations` | user, admin | `limit` 1–200 (50), `offset` | `{items[{id, title, created_at, updated_at}], limit, offset}` | `core/api/chat.py` |
| GET / DELETE | `/api/v1/conversations/{id}` | user, admin | | detail with `messages[{id, role, content, citations, refused, refusal_reason, created_at}]` / 204 | `core/api/chat.py` |
| GET | `/api/v1/admin/status` | admin | | `{version, environment, auth_mode, uptime_seconds}` | `core/api/admin.py` |
| GET | `/api/v1/admin/metrics` | admin | | Prometheus text | `core/api/admin.py` |
| GET | `/api/v1/admin/usage` | admin | `group_by` user/day (day); `from`, `to` datetime; window ≤ 92 days, default last 7 | `{group_by, start, end, rows[{key, requests, refused, prompt_tokens, completion_tokens, cost_usd, latency_p50_ms, latency_p95_ms, ttft_p50_ms, ttft_p95_ms}]}` | `core/api/admin.py` |
| GET | `/api/v1/admin/documents` | admin | | `{total, by_status{pending, processing, ready, failed}}` across all users, no names | `core/api/admin.py` |

`DocumentOut` = `{id, filename, content_type, size_bytes, status, error_code, page_count, chunk_count, created_at,
updated_at, source_url, fetched_at}`; `error_code` ∈ `encrypted, no_text, corrupt, too_large, unsupported_encoding,
max_attempts` (`core/api/schemas.py`).

**Async ingestion states:** `pending → processing → ready | failed` (`core/domain/models.py` `DocumentStatus`).
The worker claims with `FOR UPDATE SKIP LOCKED`; a claim older than `EKA_WORKER_STALE_CLAIM_MINUTES` (10) is taken over;
after `EKA_WORKER_MAX_ATTEMPTS` (3) the document becomes `failed/max_attempts` (`core/adapters/db/ingestion_queue.py`,
`core/config.py`). No webhook or callback; the client polls `GET /api/v1/documents/{id}`.

**Locator shapes** (`core/ingestion/loaders/*`, `core/ingestion/chunking.py`): PDF `{type: "page", page}`;
DOCX `{type: "section", path: [..], paragraphs: [a, b]}`; CSV `{type: "rows", start, end}`;
code/text `{type: "lines", path, start, end}` (1-based).

**Rate limits:** none in the core (no limiter in `core/api`). The edge limits per user id: burst 20, 5 req/s
(`edge/config/EdgeProperties.java` `RateLimit`), in memory per instance, or shared in Redis when
`EKA_EDGE_RATE_LIMIT_REDIS_URL` is set (`edge/ratelimit/RateLimitConfig.java`). Over limit: 429 problem
`rate-limited` + `Retry-After` (`edge/token/InternalTokenFilter.java`).

## 2. Auth

**Core, `EKA_AUTH_MODE=api_key`** (`core/security/auth.py`, `core/api/deps.py`, `core/config.py`):
header `X-API-Key`; config `EKA_API_KEYS` = `{"<user-id>": {"sha256": "<64 hex>", "role": "user|admin"}}`
(role default `user`). Only digests are stored; compare is constant time over all entries; keys > 512 chars rejected.
The JSON key **is** the owner id. No scopes; two roles only (`core/domain/models.py` `Role`).

**Core, `EKA_AUTH_MODE=gateway`** (`core/security/gateway.py`): `Authorization: Bearer <internal token>`;
algorithm **ES256 only**; key by `kid` from `EKA_GATEWAY_JWKS_URL` (PyJWKClient, cache 300 s); issuer
`EKA_GATEWAY_ISSUER` (default `eka-edge`), audience `EKA_GATEWAY_AUDIENCE` (`eka-core`); required claims
`exp, iat, sub, iss, aud`; leeway 5 s; max token 4096 chars. `sub` → owner id, `role` → role. X-API-Key is ignored.

**Edge, inbound** (`edge/security/*`, `gateway/src/main/resources/application.yml`): OIDC JWT; issuer
`EKA_EDGE_OIDC_ISSUER`; JWKS `EKA_EDGE_OIDC_JWK_SET_URI`; audience `EKA_EDGE_OIDC_AUDIENCE` (default `eka-api`),
must be in `aud`; algorithms RS256, ES256 (HS* refused, `JwtDecoderConfig.java`); clock skew 5 s; `sub` required.
Roles from claim `roles` (configurable) or Keycloak `realm_access.roles`; admin if it contains `eka-admin`
(`IdentityMapper.java`). Everything except `/actuator/health|info|jwks|prometheus` needs a token (`SecurityConfig.java`).

**Edge → core internal token** (`edge/token/InternalTokenService.java`, `EdgeProperties.java`): ES256, header `kid`,
`typ JWT`; claims `iss` (eka-edge), `aud` (eka-core), `sub` (pseudonym), `role` (user/admin), `rid` (request id),
`jti`, `iat`, `exp`; TTL default 60 s, max 60 s. Published at the edge management port `/actuator/jwks`
(port `EKA_EDGE_MANAGEMENT_PORT` 8081). Before forwarding, the edge removes `Authorization`, `Cookie`, `X-API-Key`
and any `X-Auth-*` header (`InternalTokenFilter.java`).

**Token lifetime (IdP):** Keycloak realm `accessTokenLifespan` 900 s (`keycloak/realm-eka.json`). Other IdPs: UNVERIFIED.

**Service-to-service today:** the only Keycloak client is `eka-ui` (public, direct access grants on); no client has
service accounts / client credentials (`keycloak/realm-eka.json`). There is no M2M client, no scope check and no
separate service role in edge or core. The triage agent (`ops-agent/`) does not call `/search` (UNVERIFIED beyond
its tool list in README; its tools are PromQL, health, runbook, log search).

**What a new internal caller needs (derived from the code above):**
- Through the edge: a JWT from the configured IdP, signed RS256/ES256, `iss` = configured issuer, `aud` containing
  `eka-api`, non-empty `sub`, within expiry. In Keycloak this means a new confidential client with service accounts
  enabled and the `audience-eka-api` mapper (not present today). Its owner id will be
  `"u" + first 32 hex of HMAC-SHA256(pseudonym-secret, iss + "\n" + sub)`.
- Directly to a core in `api_key` mode: an entry in `EKA_API_KEYS` and the `X-API-Key` header.
- Directly to a core in `gateway` mode: not possible without the edge's private signing key.

## 3. Tenant / owner identifier

- There is **no tenant concept**: the unit of isolation is the user (owner). No tenant column, claim or mapping table
  (grep of `core/` for tenant: none; `core/adapters/db/tables.py` uses `owner_id`).
- Source: `api_key` mode → the key's JSON name in `EKA_API_KEYS`; `gateway` mode → internal token `sub`, which the edge
  sets to the HMAC pseudonym of IdP `iss`+`sub` (`edge/security/IdentityMapper.java`). The client cannot supply it.
- Pattern `^[A-Za-z0-9_.-]{1,36}$` (`core/domain/models.py` `USER_ID_PATTERN`; repeated as DB CHECK `owner_id ~ '^[A-Za-z0-9_.-]{1,36}$'`
  in `alembic/versions/0001_initial_schema.py`). Edge pseudonyms are 33 chars (`u` + 32 hex).
- Columns: `owner_id` on documents, chunks, conversations, messages, `usage_events` (all `Text NOT NULL`)
  (`core/adapters/db/tables.py`). Postgres row-level security keyed on `app.owner_id` and `app.role`.
- Cross-owner access: **404**, never 403 (`core/api/documents.py` docstring, `core/api/errors.py`); search simply
  returns no foreign chunks. Admin role does not widen search or chat; admin only adds `/admin/*`.
- **Per-tenant owner mapping: does not exist.** A single machine identity maps to one owner and sees only documents
  uploaded under that same identity.

## 4. Config flags that matter for integration (`core/config.py`, env prefix `EKA_`)

| Name | Default | Effect |
|---|---|---|
| `AUTH_MODE` | none (required unless `ENVIRONMENT=test`) | `api_key` or `gateway` |
| `API_KEYS` | `{}` | api_key callers and roles |
| `GATEWAY_JWKS_URL` / `_ISSUER` / `_AUDIENCE` | none / `eka-edge` / `eka-core` | internal token checks |
| `ENVIRONMENT` | `local` | `prod` hides `/docs`, `/openapi.json` (`core/main.py`) |
| `REFUSAL_MIN_COSINE` | 0.50 | gate for `weak_evidence` |
| `ANSWER_MODE` | `verified` | default chat mode |
| `MAX_UPLOAD_MB`, `MAX_DOCS_PER_USER`, `MAX_TEXT_FILE_KB`, `ALLOWED_TEXT_EXTENSIONS` | 20, 200, 512, list above | upload limits |
| `RETRIEVAL_CANDIDATES`, `RRF_K`, `RERANKER_MODEL`, `RERANKER_TOP` | 30, 60, unset (off), 20 | search ranking |
| `CHAT_PROVIDER`, `CHAT_MODEL`, `CHAT_API_KEY`, `CHAT_BASE_URL` | `fake`, none, none, OpenAI URL | chat model |
| `CHAT_FALLBACKS` | `[]` (max 1) | fallback model list |
| `CHAT_PRICE_INPUT_PER_1M` / `_OUTPUT_PER_1M` | unset | cost in usage events; null when unset |
| `WEB_FALLBACK_ENABLED` | false | fetch allow-listed pages when evidence is weak |
| `WEB_ALLOWED_HOSTS`, `WEB_ENTRY_URLS` | `()`, `()` | exact hosts; 1–10 https entry URLs on those hosts (validated) |
| `WEB_REFRESH_HOURS`, `WEB_FETCH_TIMEOUT_SECONDS`, `WEB_MAX_PAGE_KB`, `WEB_INGEST_WAIT_SECONDS`, `WEB_MAX_LINKED_PAGES` | 24, 10, 2048, 30, 0 | web fallback limits |
| `STORAGE_BACKEND` | `local` | `s3` needs `S3_BUCKET` |

Edge (`application.yml`, `EdgeProperties.java`): `EKA_EDGE_CORE_URL`, `EKA_EDGE_OIDC_ISSUER`, `EKA_EDGE_OIDC_JWK_SET_URI`,
`EKA_EDGE_OIDC_AUDIENCE` (eka-api), `EKA_EDGE_PSEUDONYM_SECRET` (≥16 chars, required), `EKA_EDGE_SIGNING_KEY_FILE`
or `EKA_EDGE_EPHEMERAL_KEY=true`, `EKA_EDGE_RATE_LIMIT_REDIS_URL`, breaker `EKA_EDGE_CB_WINDOW` 20 / `_MIN_CALLS` 10 /
`_OPEN_FOR` 30s, response timeout 120 s, port `EKA_EDGE_PORT` 8080.

**Edge route table** (`application.yml`): one route `core-api`, `Path=/api/**` → `EKA_EDGE_CORE_URL`, with circuit
breaker `core`. `GET /api/v1/me` is answered by the edge itself. `/health/*` is not routed by the edge.

## 5. Events, queues, topics

- No Kafka, RabbitMQ or pub/sub in core or edge (grep of `src/`, `gateway/src/main`).
- Ingestion queue = the `documents` table (`status`, `locked_at`, `attempts`), polled every `EKA_WORKER_POLL_SECONDS`
  (2 s) (`core/adapters/db/ingestion_queue.py`, `core/config.py`). No key/headers; payload is the row.
- Triage agent on AWS: SQS queue `OPS_AGENT_ALARM_QUEUE_URL`, up to 10 messages per receive, deleted after handling;
  body is an SNS envelope (`Type: Notification`, `Message`) holding a CloudWatch alarm: `AlarmName`, `NewStateValue`
  (`ALARM` → firing, else resolved), `AlarmDescription`, `NewStateReason`; mapped to labels `alertname, severity,
  source=cloudwatch` (`ops-agent/.../alert/SqsAlarmPoller.java`, `CloudWatchAlarm.java`).
- SSE chat events: see §1.

## 6. Test counts (last real run: CI run 43393823859, commit 1e81215, all 12 jobs success)

Source: GitHub Actions log of that run (`gh run view 43393823859 --log`), repo path `actions/runs/43393823859`.

| Job | Result |
|---|---|
| Python unit (`lint-and-test`, 3.11 and 3.12) | 596 passed, 5 skipped, 79 deselected |
| Python with integration (`integration`, Testcontainers) | 672 passed, 8 skipped |
| Edge (Maven) | 47 run, 0 failed, 0 skipped |
| Ops agent (Maven) | 80 run, 0 failed, 7 skipped |
| UI unit (Vitest) | 39 passed, 4 files |
| UI browser (Playwright) | 1 passed |
| Others | terraform, monitoring, evaluation, docker-image, api-contract: success (no counts read) |

## 7. Built vs not built vs built-but-not-run-live

| Item | State | Source |
|---|---|---|
| Bedrock adapter (Converse/ConverseStream) | Built; run only against the local stand-in `eka.tools.bedrock_stub`; never called real Bedrock | `core/adapters/chat_bedrock.py`, README line 48 |
| AWS (Terraform: Fargate, RDS, S3, WAF, autoscaling, OIDC deploy role, alarms, agent service) | Built; `validate`/`fmt` only; never planned or applied | `infra/aws/*.tf`, README line 50 |
| SMTP email from triage agent | Built; delivered only to a local mail catcher | README line 189 (code path in `ops-agent/`, not read in detail: UNVERIFIED) |
| CloudWatch log search / shipping | Built; tested against LocalStack only | README lines 178, 191 |
| OpenAI-compatible chat | Built and run live (`gpt-4o-mini`) | README; `core/adapters/chat_openai.py` |
| Model fallback + per-model breaker | Built | `core/adapters/chat_fallback.py`, `core/adapters/breaker.py` |
| Token/cost/TTFT accounting | Built | `core/api/admin.py` `/usage`, `alembic/versions/0004_usage_tokens.py` |
| M2M client, tenant model, per-tenant mapping, core rate limit | Not built | §2, §3 |
| Search `scores.rerank` | Field exists, never filled | `core/api/search.py` |

## 8. README / docs vs code

| README says | Code says |
|---|---|
| API table lists admin `status` and `metrics` only (README "API") | Also `/api/v1/admin/usage` and `/api/v1/admin/documents` (`core/api/admin.py`) |
| API table "Auth: key" for every route | In `gateway` mode the core takes a bearer internal token and ignores `X-API-Key` (`core/api/deps.py`) |
| Edge "43 tests" (README line 40) | CI run 43393823859: 47 |
| Triage agent "66 tests" (README line 47) | CI: 80 run, 7 skipped |
| Web UI "32 unit tests" (line 43) | CI and README line 372: 39 |
| "Browser test on GitHub Actions ... first run still to come" (line 194) | `ui-browser` job passed in run 43393823859 |
| Search `scores.rerank` comment "set once reranking exists" | Reranking exists (`RERANKER_MODEL`), field still never set (`core/api/search.py`) |
| 401 detail "A valid API key is required." | Returned in gateway mode too, where no API key is used (`core/api/errors.py`) |

## Answer: reconcile-ai backend → `/search` through the edge

1. `POST https://<edge>/api/v1/search` with `Authorization: Bearer <IdP JWT>` and the body in §1.
2. The JWT must pass the edge: configured issuer, RS256/ES256, `aud` ⊇ `eka-api`, non-empty `sub`, not expired.
   **No IdP client exists for this today**; one must be added (confidential, client credentials, audience mapper).
3. The edge maps it to owner `u<hmac>` and role `user` (or `admin` if roles contain `eka-admin`), applies the
   per-user rate limit (20 burst, 5/s), mints a 60 s ES256 token and forwards.
4. The core returns only chunks owned by that one pseudonymous owner. Documents must be uploaded through the
   same identity. **No per-tenant owner mapping exists**; serving several reconcile-ai tenants would need either
   one IdP identity per tenant or new code.
