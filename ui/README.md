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
the tab and are not refreshed: after 15 minutes you sign in again.

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
