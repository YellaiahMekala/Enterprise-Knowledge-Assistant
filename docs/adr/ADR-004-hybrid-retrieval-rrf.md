# ADR-004: Hybrid retrieval with reciprocal rank fusion

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Experiment E2 shows hybrid does not beat dense-only beyond the interval, or latency budget is exceeded. |
| Related | FR-20, FR-21 |

## Context
Dense search misses exact identifiers and rare terms; full-text search misses paraphrase. Their scores are not comparable.

## Decision
Run dense and full-text queries and fuse by rank with RRF (k = 60). PostgreSQL full-text ranking is used; it is not true BM25.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Hybrid with RRF (chosen) | No score normalisation; robust. Cost: two queries per request. |
| Dense only | Simplest. Weaker on identifiers and exact terms. Kept as the E2 baseline. |
| Weighted score blending | Needs calibrated, comparable scores. Rejected. |

## Consequences
Two queries per request; E2 decides whether the complexity is justified.
