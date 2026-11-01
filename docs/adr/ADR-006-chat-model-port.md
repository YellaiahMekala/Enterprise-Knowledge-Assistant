# ADR-006: Chat model behind a port; OpenAI-compatible default

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | A required provider is not OpenAI-compatible, or data must not leave the deployment. |
| Related | FR-30, FR-33, R2 |

## Context
The chat provider changes more often than the rest of the system and receives retrieved passages.

## Decision
A `ChatModel` port with an OpenAI-compatible adapter. Model name, base URL and prices are configuration, never code.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Port + OpenAI-compatible adapter (chosen) | Switching compatible endpoints is configuration. Non-compatible providers need an adapter. |
| Direct SDK calls in services | Less code now; couples services to a vendor and breaks offline tests. Rejected. |

## Consequences
A local-model adapter is possible without touching services.
