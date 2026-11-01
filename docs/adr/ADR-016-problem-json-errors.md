# ADR-016: RFC 9457 problem+json for all errors

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Client requirements need a different error envelope. |
| Related | NFR-06 |

## Context
Framework default errors have inconsistent shapes and can leak structure.

## Decision
One error shape produced in one place in each service; detail logged, not returned. Gateway and core use the same shape and `request_id`.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| problem+json (chosen) | Standard, consistent. |
| Framework defaults | Inconsistent; leaks structure. Rejected. |

## Consequences
Both services convert framework errors to the same shape.
