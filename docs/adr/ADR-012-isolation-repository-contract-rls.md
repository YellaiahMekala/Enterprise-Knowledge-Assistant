# ADR-012: Isolation by repository contract plus row-level security

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | A leakage test fails, or a new access path bypasses the repositories. |
| Related | FR-02, NFR-02, AC-01 |

## Context
One forgotten filter would leak one user's document into another's answer.

## Decision
Every repository method requires `owner_id`; `owner_id` is stored on chunks; RLS with fail-closed policies; foreign ids return 404.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Repository contract + RLS (chosen) | Two independent layers. Cost: per-request `set_config`; tests must not run as superuser. |
| Application filtering only | One bug leaks data. Rejected. |
| Schema or database per user | Strong isolation; operationally heavy at this scale. Rejected. |

## Consequences
Tests run through RLS with a non-owner role.

**Implementation note (phase P1, 2026-10-31).** Every API transaction runs `SET LOCAL ROLE eka_api` and then sets `app.owner_id` and `app.role` with transaction-local `set_config`. The role switch makes the guarantee independent of how the login role was created, so even the superuser connection of the local database cannot bypass the policies; deployed profiles should still connect as a non-superuser member of `eka_api`. The roles are created `NOLOGIN` (no passwords in migrations). Tables use `FORCE ROW LEVEL SECURITY`. A transaction that sets no owner sees zero rows, and a reused pooled connection does not keep the previous owner (both tested on a real PostgreSQL).
