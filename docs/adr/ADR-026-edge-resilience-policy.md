# ADR-026: Edge resilience policy: timeouts, circuit breaker, bulkhead, no blind retries

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Chaos scenarios (Test Strategy §3.10) show the policy is too aggressive or too lax. |
| Related | FR-64, NFR-06, NFR-17 |

## Context
The edge sits between users and a core that depends on a database and a third-party model provider.

## Decision
Connect and response-header timeouts per route class; a circuit breaker on the core (opens on a failure-rate threshold, half-open probes, fast 503 with `Retry-After`); a bulkhead on concurrent streams; **retries only for idempotent GETs**, never for uploads or `POST .../messages` (not idempotent); SSE streams are never retried after the first byte. Thresholds are configuration, set from the resilience tests.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Timeouts + breaker + bulkhead, no blind retries (chosen) | Predictable failure and recovery. Needs tuning from tests. |
| Retry everything | Duplicates messages and uploads; amplifies outages. Rejected. |
| No resilience at the edge | Failures cascade to users. Rejected. |

## Consequences
Behaviour under failure is specified and tested, not left to defaults.
