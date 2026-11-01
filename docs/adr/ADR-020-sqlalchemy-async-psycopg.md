# ADR-020: SQLAlchemy 2 (async) over psycopg 3, with Alembic

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Query complexity or performance justifies a different data layer. |
| Related | FR-02, NFR-02 |

## Context
The API and the worker share one data layer; migrations need a synchronous driver.

## Decision
One async data layer, `psycopg` 3 for async and sync use, Alembic for schema, vector queries as explicit SQL.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| SQLAlchemy async + psycopg 3 (chosen) | One driver. Explicit SQL for vector queries. |
| asyncpg | A second driver is needed for migrations. Rejected. |
| Raw SQL without migration tool | Schema drift. Rejected. |

## Consequences
Repositories are written once for API and worker.
