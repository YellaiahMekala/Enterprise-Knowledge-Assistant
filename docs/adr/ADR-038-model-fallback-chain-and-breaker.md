# ADR-038: Model fallback chain with a per-model circuit breaker

| | |
|---|---|
| Status | Proposed (task P10-C) |
| Date | 2026-11-12 |
| Decision owner | Maintainer |
| Review trigger | More than two models in a chain; a need to route by task or by data class (a separate decision); failover that hides a real outage for too long. |
| Related | ADR-006, ADR-034, FR-54, NFR-17, NFR-19 |

## Context
Each chat adapter retries with exponential backoff (OpenAI on 429 and 5xx before any text; Bedrock through boto3 standard retries). Nothing fails over to a second model, so a provider outage is a user-visible 502 even when a second provider is configured. The edge has a circuit breaker for the core, but the model call has none, so every request waits for the dead provider's timeout.

## Decision
1. **A decorator, `FallbackChatModel`,** implements `ChatModel` over an ordered list of models. The answer service sees one model; the chain lives in the adapter layer.
2. **Fail over only before the first text fragment, and only on `ModelUnavailable` or `ModelTimeout`.** After text has started the stream is never moved to another model (the reader would see two answers spliced). A failure mid-stream ends in the existing SSE error event.
3. **A per-model breaker** (own code, `eka/resilience/breaker.py`): window of 20 calls, minimum 10, opens at 50% failures, open for 30 s, 3 half-open probes; the same numbers as the edge breaker. An open model is skipped without a call.
4. **Configuration** `EKA_CHAT_FALLBACKS`, a JSON list of `{provider, model, base_url?, api_key_env?}`. A key is read from the environment variable the item names, never stored in the value. First release: one fallback.
5. **Visibility.** `usage_events.model` records the model that answered. Metrics: `eka_llm_failover_total{from_model,to_model,reason}`, `eka_llm_breaker_state{model}`, `eka_llm_calls_total{model,outcome}`. Alert `EkaLlmFailoverBurst` and a runbook section, so failover does not hide an outage.

## Options considered
| Option | Assessment |
|---|---|
| Decorator over the port (chosen) | No change to the answer service; testable with scripted fakes |
| Resilience4j on a Java service in front of the model | The model calls are in the Python core; this would add a hop |
| A library breaker (pybreaker or aiobreaker) | Fewer lines to write, but an extra dependency for about 60 lines and less control over the half-open rules and clock injection |
| A model gateway such as LiteLLM | Strong, but a new service to run and secure; revisit if routing by cost or data class is added |
| Retry the same model longer | Already done per adapter; does not help in an outage |
| Switch models mid-stream | Rejected: mixed answers and double spend |

## Consequences
- During a primary outage the first requests still pay the primary's failure time; after the breaker opens they do not. The drill measures both.
- The fallback model may answer differently or worse. Answer quality per model is a separate evaluation (the provider comparison tool).
- The chain does not choose models by task or data class. That is a different decision and is not made here.
