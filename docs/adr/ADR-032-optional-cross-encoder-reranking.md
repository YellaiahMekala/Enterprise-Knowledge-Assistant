# ADR-032: Optional cross-encoder reranking, off by default

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-08 |
| Decision owner | Maintainer |
| Review trigger | A corpus of at least a few hundred documents where the evaluation shows a gain beyond one or two questions, or a latency budget that can absorb the cost. |
| Related | FR-22, ADR-004, experiment E3 |

## Context
Hybrid retrieval puts the right chunk in the top three for every evaluation question, but the first rank is right for 42 of 44. A cross-encoder reads the question and each candidate together, so it can fix the order of the top few at a cost in latency.

## Decision
Add a `Reranker` port with a fastembed cross-encoder adapter (`Xenova/ms-marco-MiniLM-L-6-v2`, 80 MB, Apache-2.0). When `EKA_RERANKER_MODEL` is set, the top `EKA_RERANKER_TOP` (20) fused candidates are re-scored and re-ordered. The model loads on first use. The refusal gate still uses the dense cosine, so it is unaffected. **The default is off.**

## Measured (experiment E3: 44 questions, 13 documents, one chunk each, same run)
| Configuration | Hit@1 | Hit@3 | MRR |
|---|---|---|---|
| Hybrid | 95.5% | 100% | 0.977 |
| Hybrid + rerank | 100% | 100% | 1.000 |

Latency: about 560 ms median for 20 passages of about 130 tokens on a laptop CPU, measured once with five repetitions, which is more than half of the 1 s search SLO.

## Options considered
| Option | Assessment |
|---|---|
| Off by default, switchable (chosen) | No cost for deployments that do not need it. The result is recorded, and the experiment can be repeated on a larger corpus. |
| On by default | Two questions out of 44 on a 13-chunk corpus is too small to justify about 560 ms on every search. |
| Not built | Leaves FR-22 unanswered and no evidence either way. |
| Hosted reranker API (Cohere, Voyage) | Sends passages to a third party and adds a cost per query. Possible behind the same port. |

## Consequences
The first rank improved in this run, but 2 of 44 on 13 chunks is within noise: the ceiling is 100% and the corpus is easy. Turning it on needs a larger evaluation set. A GPU, or a smaller `EKA_RERANKER_TOP`, would reduce the latency.
