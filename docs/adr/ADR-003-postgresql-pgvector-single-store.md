# ADR-003: PostgreSQL with pgvector as the only core datastore

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Filtered recall or latency targets cannot be met after the mitigations in TDD §4.6, or the database becomes the scaling bottleneck. |
| Related | FR-02, FR-20, NFR-02, ADR-012 |

## Context
The core needs documents, chunks, vectors, full-text search, conversations, usage events and an ingestion queue, with strict per-user isolation.

## Decision
One PostgreSQL with the pgvector extension holds all core state, including the ingestion queue.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| PostgreSQL + pgvector only (chosen) | One store, SQL filters, row-level security, one backup. Risk: filtered approximate-search recall (managed in TDD §4.6). |
| Chroma local + pgvector deployed | Mirrors a reference course project. Two backends to test; behaviour differs between environments. Rejected. |
| Qdrant + PostgreSQL | Strong payload filtering. Two stores to keep consistent (dual writes). Rejected for v1. |

## Consequences
A single isolation model; the filtered-ANN risk (BRD R1) must be tested.
