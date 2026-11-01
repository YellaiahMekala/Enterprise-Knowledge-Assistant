# ADR-030: Allowlisted web fallback for official documentation (optional, Planned)

| | |
|---|---|
| Status | Proposed |
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
