# ADR-009: Refusal gate before the model, on a calibrated signal

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | The embedder or reranker changes (threshold must be re-calibrated), or false-refusal rate exceeds target. |
| Related | FR-32, AC-02 |

## Context
RRF scores are rank-based and carry no evidence strength; prompt-only refusal pays for every bad question and models often answer anyway.

## Decision
Refuse without calling the model when the best cosine (or rerank score) is below a threshold chosen by experiment E4. The prompt also defines the `INSUFFICIENT_EVIDENCE` sentinel.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Calibrated retrieval gate + sentinel (chosen) | Saves cost; threshold must be calibrated per model. |
| Prompt only | No calibration. Pays for every bad question; unreliable. Rejected. |
| Gate on RRF score | Not an evidence measure. Rejected. |

## Consequences
The gate stays off, with a startup warning, until E4 sets a threshold.
