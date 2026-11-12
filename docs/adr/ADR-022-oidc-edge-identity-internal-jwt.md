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
5. SPA sign-in uses authorization code with PKCE against the identity provider. The development identity provider (candidate: Keycloak; alternative: a minimal test issuer) is chosen and verified in spike S-4 (pulled forward to right after milestone M1). Built 2026-11-11 against Keycloak: the UI's `sso` build signs in with the authorization code flow and PKCE without a library (`ui/src/app/oidc.ts`), checks state and nonce, uses each verifier once, and sends the access token to the edge. There is no refresh token handling; the user signs in again after the 15-minute token expires.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| OIDC at the edge + internal JWT (chosen) | Standard, auditable, rotatable keys, no shared secret. Cost: JWT library in the core (PyJWT + cryptography) and a dev identity provider. |
| Core validates the user's JWT directly | No token exchange. Duplicates OIDC logic in the core and exposes the core to the public token. Rejected. |
| HMAC identity headers (ADR-011) | Shared secret, custom, no standard claims. Superseded. |
| mTLS only | Strong transport identity but carries no user claims. Kept as a transport layer, not a replacement. |

## Consequences
Key rotation uses a JWKS overlap window (Operational Readiness). Replay is limited by the 60-second lifetime, the private network and mutual TLS in deployed profiles. The `jti` is **not** checked for replay and the design makes no replay-prevention claim; the core keeps no replay cache in v1 (residual risk R-05 in the threat model). A bounded replay cache for sensitive actions is Proposed if a deployment needs it. Updated 2026-10-31 after an external review.

**Update 2026-11-11 (UI token refresh).** The browser now keeps the refresh token next to the access token (tab-scoped `sessionStorage`) and swaps it for a new pair when the access token has expired, before the next request. The realm rotates refresh tokens (`revokeRefreshToken`, no reuse) and limits the session to 30 idle minutes and 8 hours. Checked against the real Keycloak and edge: a refreshed token is accepted, a reused refresh token is refused, and after a reuse attempt the newer refresh token is refused too. The trade-off: a refresh token in browser storage is readable by script on the page, like the access token already was; rotation and the session limits bound what a stolen one is worth. A backend-for-frontend with an HTTP-only cookie would remove it from the browser and is not built.

**Update 2026-11-12 (renewal before expiry).** Renewal no longer waits for a request to find the token expired. `SessionService.keepFresh` sets one timer for the current token, one minute before its expiry time (which is already 30 seconds before the real one), and every stored or cleared session replaces it. The timer uses the same single shared renewal as the request path, so a request and the timer never spend the single-use refresh token twice. A failed renewal signs out. A timer longer than the browser limit is clamped and looks again when it fires, and a tab that slept past the due time schedules again when it becomes visible. API-key sessions have no timer. Checked: 7 fake-timer tests and a real Chrome run against Keycloak and the edge (idle page, one refresh grant, rotated tokens, next request on the new token).
