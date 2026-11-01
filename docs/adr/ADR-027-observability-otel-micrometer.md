# ADR-027: Observability with OpenTelemetry trace context and Prometheus metrics

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | The observability backend changes or trace volume needs sampling policy changes. |
| Related | FR-65, NFR-07, ADR-028 |

## Context
A request crosses the edge, the core, the database and a model provider; diagnosing latency or errors needs one trace and one request id.

## Decision
W3C `traceparent` propagation from the edge to the core and to logs; edge metrics through Micrometer to Prometheus; core metrics through `prometheus-client`; tracing through OpenTelemetry on both sides (Java: Micrometer Tracing with the OpenTelemetry bridge; Python: OpenTelemetry SDK and FastAPI instrumentation, which is published as pre-1.0 releases). Metrics are never labelled by user id.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| OTel + Prometheus (chosen) | Vendor-neutral, standard. Python instrumentation packages are pre-1.0; pin and test. |
| Logs only | Cheap; slow to diagnose. Rejected. |
| Vendor APM agent | Fast to start; vendor lock-in and cost. Rejected. |

## Consequences
Trace and request ids appear in every log line and every audit record.
