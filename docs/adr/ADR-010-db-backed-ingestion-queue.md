# ADR-010: Database-backed ingestion queue with a separate worker

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Queue depth or polling load becomes visible, or ingestion needs fan-out beyond database throughput. |
| Related | FR-16, NFR-06 |

## Context
Parsing and embedding are CPU-bound and must survive restarts.

## Decision
Documents are claimed with `FOR UPDATE SKIP LOCKED`; the worker is the same image with another command.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| DB queue + worker (chosen) | No new infrastructure, transactional with data. Lower throughput than a broker. |
| In-process background tasks | Simplest. Restart loses work; CPU competes with requests. Rejected. |
| Message broker | Scales further; extra infrastructure for v1 volumes. Revisit later. |

## Consequences
Simple and recoverable; throughput bounded by polling and the database.
