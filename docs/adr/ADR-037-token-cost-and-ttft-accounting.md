# ADR-037: Token, cost and time-to-first-token accounting

| | |
|---|---|
| Status | Proposed (task P10-B) |
| Date | 2026-11-12 |
| Decision owner | Maintainer |
| Review trigger | A provider that returns no usage; more than about 100 distinct models or providers (label cardinality); a request for per-user budgets or quotas. |
| Related | ADR-006, ADR-034, FR-50, FR-53, NFR-03, NFR-05 |

## Context
Usage events hold prompt and completion size in characters only. The providers return exact token counts, which are discarded. Time to first token (NFR-03: p95 under 3 s) is not measured, and cost per user is unknown.

## Decision
1. **Take token counts from the provider.** `ChatModel.complete` and `stream` get an optional keyword argument `usage` (a collector the adapter fills). OpenAI-compatible: `stream_options.include_usage` and the usage object. Bedrock: `usage` in Converse and the `metadata` event in ConverseStream. The offline model estimates (characters / 4) and marks the source `estimated`.
2. **Price from settings, never from code.** `EKA_CHAT_PRICE_INPUT_PER_1M` and `EKA_CHAT_PRICE_OUTPUT_PER_1M`. With no price the cost is empty, not zero.
3. **Two first-token times.** `ttft_ms` is request start to the first provider token. `answer_ttfb_ms` is request start to the first text the client can see; in verified mode that includes buffering and citation checks, so it is larger and is the number a user feels.
4. **Metrics without user labels; per-user figures from the database.** Prometheus series are labelled by provider, model and outcome only (`eka_llm_tokens_total`, `eka_llm_cost_usd_total`, `eka_llm_ttft_seconds`, `eka_llm_request_duration_seconds`). Per-user and per-day totals come from `usage_events` through an admin-only `GET /api/v1/admin/usage`.

## Options considered
| Option | Assessment |
|---|---|
| Provider counts through an optional collector (chosen) | Small change to the port; fakes and old callers keep working |
| Change `complete` to return `(text, usage)` | Cleaner types, but breaks every caller and test double in one step |
| Count tokens locally with a tokenizer | Needs a tokenizer per model family and is still an estimate |
| A user id label on Prometheus series | Unbounded cardinality: one series per user per metric. Rejected |
| A separate metering service | More to run than this size needs |
| OpenTelemetry metrics instead of prometheus_client | Revisit together with tracing (FR-65); not needed for this change |

## Consequences
- The usage table gains nullable columns; old rows stay valid.
- A provider that streams without usage yields `estimated` counts; the source column says so, and reports must not present them as billed tokens.
- Cost is an estimate from configured prices, not an invoice.
- Admin sees counts, tokens and cost, never text (the existing row-level security admin clause already limits what admin can read).
