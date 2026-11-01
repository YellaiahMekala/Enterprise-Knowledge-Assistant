# ADR-025: Edge rate limits and concurrency quotas, in-memory in v1

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | The edge runs more than one replica, or abuse is observed. |
| Related | FR-62, NFR-05 |

## Context
Model calls are the variable cost and an abuse target. The edge sees the authenticated user before the core does.

## Decision
Per-user limits on requests per minute (stricter on `POST .../messages` and uploads), a per-user concurrent-stream cap (bulkhead) and an edge request-size cap. Implementation: an in-memory token bucket per instance (library choice at implementation). Violations return 429 with `Retry-After` and a problem+json body and never reach the core.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| In-memory per instance (chosen) | No new infrastructure. With N replicas the effective limit is N times higher; documented. |
| Redis-backed limiter | Correct across replicas; adds a Redis dependency. Proposed for multi-replica deployments. |
| Core-side limits only | Pays for authentication and parsing before rejecting. Rejected. |

## Consequences
The multi-replica limitation is a stated residual risk.
