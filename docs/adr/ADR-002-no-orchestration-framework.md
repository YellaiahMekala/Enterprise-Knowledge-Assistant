# ADR-002: No orchestration framework in v1; LangChain only if required

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | When a component cannot be written and tested reasonably without a framework, or when framework maintenance cost drops below custom code cost. |
| Related | FR-20, FR-30, FR-31 |

## Context
Retrieval, prompt assembly, citation validation and refusal each need exact control (isolation, citations, gate). The project owner asked for LangChain only if required.

## Decision
Custom pipeline behind ports. Admission rule: a framework piece (for example `langchain-text-splitters`) is adopted only for a specific component that cannot reasonably be written and tested without it, and only behind a port.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Custom pipeline (chosen) | Full control of control flow and tests. Cost: more first-party code. Risk: reinventing solved problems (mitigated by keeping components small). |
| LangChain as backbone | Fast start, wide recognition. Hides control flow, large dependency surface, API churn. Rejected. |
| LlamaIndex as backbone | Strong ingestion abstractions. Same concerns as LangChain. Rejected. |

## Consequences
More code to test; less framework to learn; ports keep a later adoption cheap.
