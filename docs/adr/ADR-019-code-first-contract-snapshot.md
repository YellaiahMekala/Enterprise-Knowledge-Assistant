# ADR-019: Code-first contracts with committed snapshots in CI

| | |
|---|---|
| Status | Proposed (extended in v0.2) |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Contract-first tooling is adopted, or a second consumer needs generated clients. |
| Related | NFR-08, FR-67 |

## Context
Hand-maintained specs drift. v0.2 adds a second service and an internal contract.

## Decision
Each service generates its OpenAPI; snapshots (`docs/openapi.json` for the core, the gateway's external and internal contracts under `docs/contracts/`) are committed and CI fails on any difference. A contract test exercises the internal token and the proxied routes from both sides.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Code-first + snapshot (chosen) | Cannot drift silently. Snapshot noise on intentional changes. |
| Hand-maintained spec | Drifts. Rejected. |
| No snapshot | Changes unnoticed. Rejected. |

## Consequences
Intentional contract changes show up in review as a snapshot diff.
