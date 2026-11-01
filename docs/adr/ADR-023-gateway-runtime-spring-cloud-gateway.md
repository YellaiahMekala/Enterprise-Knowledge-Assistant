# ADR-023: Gateway runtime: Spring Cloud Gateway (WebFlux), subject to a spike

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Spike S-1 fails, or the filter chain becomes harder to test than plain code. |
| Related | FR-64, ADR-014, ADR-021 |

## Context
The edge must pass SSE through without buffering, propagate client cancellation upstream, and apply filters (authentication, token exchange, rate limit, audit, circuit breaker).

## Decision
Use Spring Cloud Gateway on WebFlux (starter `spring-cloud-starter-gateway-server-webflux`, available in the 4.3.x and 5.0.x lines). Custom global filters implement token exchange, audit and limits; routes and the circuit breaker are configuration. **Spike S-1 (0.5 day, pulled forward to right after milestone M1)** against a stub upstream must show: no buffering, first event delivered before upstream completes, upstream cancelled within seconds of client disconnect, headers and trace context forwarded. If S-1 fails, fall back to Spring MVC on virtual threads with an explicit streaming proxy.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Spring Cloud Gateway WebFlux (chosen, subject to S-1) | Built-in routing, SSE passthrough, circuit-breaker filter. Reactive programming model to test and debug. |
| Spring MVC (virtual threads) + RestClient/WebClient proxy | Familiar blocking style. Streaming proxy and cancellation are hand-written. Fallback. |
| Envoy or nginx as the edge | Mature proxies; do not demonstrate Java edge ownership. Rejected for this project. |

## Consequences
Blocking calls (audit writes) must be moved off the event loop (ADR-024).
