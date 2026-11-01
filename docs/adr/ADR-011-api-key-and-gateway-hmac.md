# ADR-011: API key now, signed gateway headers later (original decision)

| | |
|---|---|
| Status | Superseded by ADR-022 |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Superseded; kept as a record. |
| Related | ADR-022 |

## Context
v0.1 assumed the Spring Boot gateway was design only and specified API-key authentication now plus an HMAC-signed identity header contract for later.

## Decision
`X-API-Key` mapped to a user id and role (digests, constant-time compare). A shared-secret HMAC identity header for the gateway.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| API key + HMAC header (original) | Simple. The HMAC part is a custom scheme with a shared secret: no key rotation story, no standard claims, easy to get subtly wrong. Superseded. |
| JWT in the Python service now | Needs issuer and key management with no consumer yet. |
| Trust a bare user-id header | Insecure if reachable. Rejected. |

## Consequences
The API-key mode survives as the core's standalone mode (ADR-022). The HMAC scheme is dropped in favour of standards.
