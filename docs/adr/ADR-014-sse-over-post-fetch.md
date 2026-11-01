# ADR-014: Streaming over POST with fetch, not EventSource

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | The browser gains header support in an event-stream API, or WebSocket is needed for two-way features. |
| Related | FR-33, FR-40 |

## Context
`EventSource` supports only GET and no custom headers, so it cannot carry an `Authorization` header or a request body.

## Decision
SSE framing over a POST response; the Angular client reads it with `fetch` and a stream reader.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| SSE over POST + fetch (chosen) | Works with bearer tokens and bodies. A small stream parser to maintain and test. |
| WebSocket | More machinery for one-way output. Rejected. |
| Token in query string with EventSource | Leaks into logs. Rejected. |

## Consequences
The gateway must pass SSE through without buffering (ADR-023).
