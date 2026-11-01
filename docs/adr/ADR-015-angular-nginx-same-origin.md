# ADR-015: Angular frontend served by nginx on the same origin

| | |
|---|---|
| Status | Accepted (amended by ADR-022) |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | CORS or CSP needs change, or the UI is deployed separately from the edge. |
| Related | FR-40 |

## Context
A same-origin deployment removes CORS configuration and lets nginx set the Content-Security-Policy.

## Decision
Angular standalone-component app built to static files and served by nginx. **Amendment:** nginx proxies `/api` to the **gateway**, not to the core.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Angular on nginx (chosen) | Same origin; one more container and a Node toolchain. |
| React | Not chosen by the owner. |
| Serve the SPA from FastAPI | Couples release cycles. Rejected. |

## Consequences
The UI authenticates through OIDC (ADR-022), not with an API key.
