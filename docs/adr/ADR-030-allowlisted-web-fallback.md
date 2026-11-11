# ADR-030: Allowlisted web fallback for official documentation (optional, built, off by default)

| | |
|---|---|
| Status | Accepted, implemented 2026-11-11 |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | The static corpus answers enough questions that the fallback is unused, or a threat-model review finds the residual risk unacceptable. |
| Related | FR-37, AC-23, R15, ADR-008, ADR-009, Threat Model (web fallback rows) |

## Context
The owner wants questions the static corpus cannot answer to be answered from official documentation sites they list. This is a new capability: it fetches content from the internet on behalf of a user, which adds an outbound request path (SSRF risk) and a new source of untrusted text (prompt injection).

## Decision
1. Build it as an optional phase (P4b) after milestone M2, disabled by default (`WEB_FALLBACK_ENABLED=false`). Nothing is built until the owner approves the phase.
2. Trigger it only when the refusal gate reports weak evidence from the user's own documents. The static corpus is always tried first.
3. Fetch only from an **exact-hostname allowlist** supplied by the owner, over HTTPS, with DNS resolution checked against private, loopback, link-local and metadata ranges and the connection made to the checked address. Every redirect hop is re-checked. Response size, total time and content type are capped. No credentials or user data are sent.
4. Fetched text is **untrusted**: it is stored as a document owned by the asking user with `source_url` and `fetched_at`, chunked and embedded like any document, tagged and neutralised in the prompt, and never treated as instructions.
5. Citations from fetched pages are typed `web` (URL and fetch date), distinct from document citations. Evaluation reports the static hit rate and the fallback rate separately.
6. v1 does not call a public search engine; it works from owner-configured entry URLs or sitemaps.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Allowlisted fetch with caching as documents (chosen) | Bounded attack surface, reproducible, cached answers become normal retrieval. Cost: SSRF and injection controls and tests; roughly 2.5 days. |
| Open web search | Broad coverage; unbounded content and injection risk, no provenance guarantee. Rejected. |
| Static corpus only | Safest and cheapest. Cannot answer questions outside the owner's library. Kept as the default when the fallback is off. |
| Let the model browse (tool calling) | Flexible; hands control of outbound requests to model output. Rejected for v1. |

## Consequences
New threats are recorded (SSRF, redirect escape, injection through pages, allowlist bypass, cost and abuse) with a test per control. The BRD marks FR-37 Planned (optional). If time is short, this phase is the first to be cut.

## Implementation (2026-11-11)
- **Fetcher** (`adapters/web_fetch.py`): https only, no user info, exact host match; every address the name resolves to must be public (`is_global`, IPv4-mapped IPv6 unwrapped, multicast refused), and the request goes to the checked address with the host name kept for SNI and certificate checks, so DNS cannot change the target between check and connect. Proxies from the environment are ignored. Up to 3 redirects, each checked like the first URL; HTML or plain text only; size cap (`EKA_WEB_MAX_PAGE_KB`, 2 MB) and one total time limit (10 s). Refusals have fixed reason codes that are logged with the host only.
- **Storage:** the page becomes Markdown (scripts, styles, navigation and forms dropped; headings, lists and code blocks kept) with a header naming the source and fetch time, uploaded through the normal upload path as the asking user's document. Migration 0003 adds `source_url` and `fetched_at` with a check that both are set together and the URL is https. The API role cannot write chunks (ADR-012), so the worker indexes the page like any upload; the request waits up to 30 s for it, then searches only the new pages. A newer copy replaces an older one once it is ready.
- **When:** only when the best cosine is below the refusal gate or nothing was found, and only for entry URLs with no copy younger than `EKA_WEB_REFRESH_HOURS`. A fresh copy is part of normal search already, so it is not fetched again.
- **Prompt and citations:** web passages are sent with their URL and `origin="web page"`, inside the same data tags as documents; citations carry `kind: "web"`, `source_url` and `fetched_at`, and the answer carries `web_fallback: true`.
- **Not done:** a search engine or crawling (v1 uses entry URLs only), a live model run, and separate fallback-rate reporting in the evaluation (the answer field is there; the harness does not count it yet).
