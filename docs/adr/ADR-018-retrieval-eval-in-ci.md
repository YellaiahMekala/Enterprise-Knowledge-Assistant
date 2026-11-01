# ADR-018: Retrieval evaluation in CI; model-judged evaluation manual

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | CI time becomes prohibitive, or a deterministic judge becomes available. |
| Related | FR-51, O5 |

## Context
Quality claims need regression protection that is free and deterministic.

## Decision
CI runs retrieval, refusal-gate and leakage metrics with the real local embedder and a Testcontainers PostgreSQL. Model-judged answer quality is a manual, recorded step.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Retrieval eval in CI (chosen) | Deterministic, offline. Answer-text quality is not regression-tested. |
| Model-judged eval in CI | Needs a key and money; non-deterministic. Rejected as a gate. |

## Consequences
Faithfulness is reported separately and never presented as a CI result.
