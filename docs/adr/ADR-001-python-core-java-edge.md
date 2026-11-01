# ADR-001: Python core for model-side work, Java edge for enterprise concerns

| | |
|---|---|
| Status | Accepted (amended by ADR-021) |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Core: if the model-side library ecosystem moves away from Python. Edge: see ADR-021. |
| Related | ADR-021, ADR-022 |

## Context
Model-side libraries (embeddings, rerankers, parsers, evaluation) are Python-first. Identity, rate limiting, audit and API lifecycle are conventionally owned by a Java edge in regulated enterprises.

## Decision
The RAG core is Python and FastAPI. Enterprise edge concerns belong to a Spring Boot service. **Amendment:** the original text left the edge as design only; ADR-021 supersedes that sentence and delivers the edge as a vertical slice.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Python core + Java edge (chosen) | Each runtime does what it is best at. Cost: two build systems and two test suites. Risk: contract drift between services (mitigated by ADR-019 and contract tests). |
| Java only | One runtime. Weaker model-side ecosystem; would re-implement parsing and evaluation. Rejected. |
| Python only | Lowest cost. Leaves identity, rate limiting and audit inside the model service and omits the enterprise-integration concern. Rejected for this project's goals. |

## Consequences
The Python core must stay secure on its own (API-key mode) and must never be reachable from outside in edge mode.
