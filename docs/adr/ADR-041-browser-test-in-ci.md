# ADR-041: A Playwright browser test in CI against a real core

| | |
|---|---|
| Status | Accepted (task P16-C, built 2026-11-13) |
| Date | 2026-11-13 |
| Decision owner | Maintainer |
| Review trigger | The browser job becomes slow or flaky enough to be ignored; more flows need covering (each new flow is a new test, not a longer one); the edge (OIDC) sign-in needs a browser test. |
| Related | ADR-015, ADR-018, FR-15, NFR-14 |

## Context
The UI had unit tests (`ng test`, 39 tests) and the API had integration tests, but nothing checked that the built pages, the proxy, the API key sign-in, the upload, the indexing badge and the streamed, cited answer work together in a browser. That was checked by hand before releases.

## Decision
1. **Playwright (`@playwright/test` 1.65) with Chromium,** one test file `ui/e2e/smoke.spec.ts`, one worker, a 6 minute limit (the worker downloads the embedding model on its first start).
2. **A real core with the fake chat model.** `ui/e2e/stack.sh up` starts db, migrate, api and worker in their own compose project (`eka-e2e`), so a developer's data is never touched. Each run gets a fresh database password and API key; only the key's SHA-256 goes into the core's config. The key file and env file are git-ignored. `stack.sh down` removes the project and its volumes.
3. **The UI** is served by `ng serve` with the existing proxy to `localhost:8000` (Playwright's `webServer`), the same path a developer uses.
4. **One flow:** a wrong key is refused; the right key reaches the chat page; a Markdown file is uploaded and its badge reaches `ready`; a question gets an answer with "24 days" and a citation to the file; an off-topic question shows "Not answered"; the conversation is listed; sign out, and `/chat` goes back to the login page. The test fails on any browser console error except the one expected 401.
5. **CI job `ui-browser`** runs after the `ui` job. On failure it prints the core's logs and uploads the Playwright report, screenshot and trace.

## Options considered
| Option | Assessment |
|---|---|
| Playwright, real core, fake model (chosen) | Covers the whole path with no paid calls; answers are fixed, so assertions are stable |
| Cypress | Works too; Playwright's tracing and its `webServer` option made the CI job shorter |
| Mocked API (route interception) | Fast, but would not catch the proxy, the SSE format or the worker |
| Through the edge with OIDC sign-in | Needs an identity provider in CI; a separate test if needed |
| A real chat model | Paid, and the answer text would vary |

## Consequences
- The first run of the job takes a few minutes (image build and the embedding model download). Later runs passed in 14 to 23 seconds of test time locally.
- The test found a real bug: the login stored the key before checking it, so a wrong key signed the app in for a moment and the shell's admin check sent the rejected key a second time (two 401s). The login now checks the key with `GET /v1/me` first and stores it only when accepted.
- Not yet run on GitHub Actions at the time of writing; checked locally (6 passes in a row).
