# ADR-008: Citations resolved and validated on the server

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | A model-judged evaluation shows frequent valid-but-wrong references that need a stronger check. |
| Related | FR-31, AC-03 |

## Context
Model-emitted quotes can be altered or invented.

## Decision
The model emits only `[n]` references. The server maps them to retrieved chunks and builds each citation (document, locator, exact passage) from stored data. An answer with no valid reference is recorded as a refusal.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Server-side resolution (chosen) | A fabricated passage is impossible. A wrong but valid reference is still possible. |
| Model quotes text | Easy; unverifiable. Rejected. |

## Consequences
Groundedness judging stays on the evaluation roadmap.
