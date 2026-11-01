# ADR-022: Standards-based edge identity: OIDC resource server and internal JWT

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | A deployment needs mTLS-only trust, token exchange with an external STS, or multi-tenant claims beyond a single user id. |
| Related | FR-01, FR-60, FR-61, FR-66, ADR-011, ADR-021 |

## Context
ADR-011's HMAC identity header was a custom scheme with a shared secret. With a real edge, standard mechanisms are available and are what reviewers expect.

## Decision
1. Browser → edge: OAuth2/OIDC bearer JWT. The edge is an OAuth2 resource server: validates signature (JWKS), issuer, audience, expiry and an algorithm allow-list (no `none`, no HS* with public keys).
2. Edge → core: the edge mints a short-lived (≤ 60 s) internal JWT signed with an asymmetric key. Claims: `iss`, `aud=eka-core`, `sub` (user id), `role`, `jti` (audit and log correlation only), `iat`, `exp`, request id. The core validates signature via the edge's public key (JWKS endpoint or mounted key), audience, issuer and expiry, and sets `owner_id` from `sub`.
3. The core is on a private network only; no published port in edge mode. mTLS between the services is a requirement for deployed environments (Proposed profile), not for local Compose.
4. The core keeps API-key mode (`AUTH_MODE=api_key`) for standalone use, tests, Postman and the evaluation harness. In `AUTH_MODE=gateway` it accepts internal tokens only.
5. SPA sign-in uses authorization code with PKCE against the identity provider. The development identity provider (candidate: Keycloak; alternative: a minimal test issuer) is chosen and verified in spike S-4 (pulled forward to right after milestone M1).

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| OIDC at the edge + internal JWT (chosen) | Standard, auditable, rotatable keys, no shared secret. Cost: JWT library in the core (PyJWT + cryptography) and a dev identity provider. |
| Core validates the user's JWT directly | No token exchange. Duplicates OIDC logic in the core and exposes the core to the public token. Rejected. |
| HMAC identity headers (ADR-011) | Shared secret, custom, no standard claims. Superseded. |
| mTLS only | Strong transport identity but carries no user claims. Kept as a transport layer, not a replacement. |

## Consequences
Key rotation uses a JWKS overlap window (Operational Readiness). Replay is limited by the 60-second lifetime, the private network and mutual TLS in deployed profiles. The `jti` is **not** checked for replay and the design makes no replay-prevention claim; the core keeps no replay cache in v1 (residual risk R-05 in the threat model). A bounded replay cache for sensitive actions is Proposed if a deployment needs it. Updated 2026-10-31 after an external review.
