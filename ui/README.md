# EKA web UI

Angular 22 app for the Enterprise Knowledge Assistant: document upload and status, chat with streamed
answers and citations, conversation list.

## Sign-in modes

How the UI signs in is chosen when it is built or served (`src/app/auth-config.ts`, replaced by
`auth-config.sso.ts` in the `sso` configuration).

| Mode | Command | Sends | To |
|---|---|---|---|
| API key (default) | `npm start` | `X-API-Key` | the core on :8000 (`proxy.conf.json`) |
| Single sign-on | `npm run start:sso` | `Authorization: Bearer <access token>` | the edge on :8080 (`proxy.edge.conf.json`) |

Single sign-on uses the authorization code flow with PKCE against Keycloak, without a client secret
or a library (`src/app/oidc.ts`). It checks the `state` and the id token's `nonce`, uses each PKCE
verifier once, and on sign-out also ends the Keycloak session. Tokens stay in `sessionStorage` for
the tab. When the 15-minute access token has expired, the next request first swaps the refresh token
for a new pair (`SessionService.fresh`, one renewal shared by concurrent requests); Keycloak rotates
refresh tokens, so each works once. If the renewal fails (30 idle minutes, 8 hours, or a reused
token) the session is cleared and the request's 401 leads back to the sign-in page.

Web citations (from the optional web fallback) show the page link and its fetch date instead of a
file name.

Before `npm run start:sso`:

1. Start the edge and Keycloak from the repository root:
   `docker compose --profile edge --profile idp up -d --build`.
2. Add `127.0.0.1 keycloak` to the hosts file. Keycloak always issues tokens as
   `http://keycloak:8180`, which is the issuer the edge checks.
3. Sign in as `alice` or `boss` with the passwords from the root `.env`.

## Commands

```bash
npm ci
npm start                     # http://localhost:4200, API key
npm run start:sso             # http://localhost:4200, single sign-on
npm test                      # unit tests (Vitest), 26
npx ng build                  # default build into dist/
npx ng build --configuration sso
```
