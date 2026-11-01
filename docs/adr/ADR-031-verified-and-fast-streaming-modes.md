# ADR-031: Verified (default) and fast streaming modes

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Measured time-to-first-token in verified mode misses the objective for real users, or validated-citation failures in fast mode are frequent enough to hurt trust. |
| Related | FR-31, FR-33, FR-38, AC-22, BRD R5, ADR-008, ADR-014 |

## Context
The v0.2 design streamed tokens and validated citations afterwards, replacing the text with a refusal if validation failed. That means a user can briefly see an answer that the server then retracts. An external review flagged this as a trust problem for a project whose selling point is verified citations.

## Decision
Offer two modes, selected by configuration (`STREAM_MODE`) and, later, per request:
1. **Verified (default).** The core buffers the model output, validates citations against the retrieved set, and only then releases the `token` events and `done`. The client never sees text with an invalid citation.
2. **Fast (optional).** Tokens stream at once, each marked `provisional: true`. The final `done` event carries `verified` and either confirms the text or replaces it with a refusal (`no_valid_citation`). The UI must label provisional text as unconfirmed.
3. `done` always reports `mode` and `verified`. The time-to-first-token objective applies to fast mode; verified mode is measured on time to complete answer.
4. Cancellation works in both modes: a client disconnect cancels the provider call and any buffered output is discarded.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Two modes, verified default (chosen) | Correctness first; the trade-off is explicit and testable. Cost: two code paths and a UI state. |
| Always stream, correct afterwards (v0.2) | Best perceived latency. Users can read text that is later retracted. Replaced. |
| Always buffer | Simplest and safest. Loses the streaming experience entirely. Rejected: fast mode is a legitimate choice for low-risk use. |
| Validate incrementally per sentence | Lower latency with some safety. Citations often follow the sentence; partial validation is unreliable. Not pursued. |

## Consequences
Tests assert that in verified mode an invalid citation never reaches the client, and that in fast mode the provisional label is present until `done`. The evaluation reports the latency cost of verified mode.
