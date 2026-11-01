# ADR-024: Edge audit trail: fail-closed for sensitive actions, best-effort otherwise

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | A compliance requirement fixes retention or tamper-evidence, or audit write latency shows in the SLO. |
| Related | FR-63, NFR-14 |

## Context
An audit trail must be durable for sensitive actions, but blocking every request on an audit write couples availability to the audit store. An outbox pattern needs a business transaction to pair with; the edge has none.

## Decision
Two classes. **Sensitive** (authentication failures, document upload and delete, admin routes): the audit record is written **before** the request is forwarded; if the audit store is unavailable the request is refused with 503 (fail closed). **Other** requests: recorded through a bounded in-memory queue with batched inserts; overflow increments a dropped-events counter that has an alert. Records hold user id, role, route, method, status, request id, trace id, timestamp and outcome. They never hold document or question text. Storage: an `audit_events` table in the edge's own schema, append-only (insert-only role). JDBC calls run on a dedicated bounded scheduler. An outbox relay to an external sink (for example a message broker) is Proposed for downstream consumers.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Two-class audit (chosen) | Durability where it matters without coupling all traffic. Cost: two code paths; risk of lost non-sensitive events on crash (documented). |
| Synchronous for every request | Strongest durability; availability tied to audit store and latency added to every call. Rejected. |
| Logs only | Cheapest; not queryable or tamper-resistant. Rejected as the audit mechanism (logs remain for diagnostics). |
| Transactional outbox | Right pattern when publishing events from a business transaction; the edge has none. Deferred to the downstream relay. |

## Consequences
Fail-closed is a deliberate availability trade-off (BRD R12). Tamper-evidence (hash chaining) is Proposed.
