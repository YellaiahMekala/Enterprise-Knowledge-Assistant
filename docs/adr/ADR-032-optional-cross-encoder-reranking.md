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

## Update 2026-11-18 (D1.2.5): larger evaluation, default stays off
The review trigger asked for a larger evaluation set. It now has 96 answerable questions (52 added, synthetic, author-written, 33 labelled hard) and 24 unanswerable, run at two chunk sizes with a decision rule fixed before the run (`python -m eka.eval.rerank_study`, report `eval/reports/e3_rerank_study.md`).

| Configuration | Hit@1 | MRR (95% interval) | nDCG@10 | Search p50 / p95 |
|---|---|---|---|---|
| 256 tokens, 13 chunks, off | 93.8% | 0.967 (0.939 to 0.990) | 0.976 | 16 / 23 ms |
| 256 tokens, on | 99.0% | 0.995 (0.984 to 1.000) | 0.996 | 745 / 1526 ms |
| 64 tokens, 34 chunks, off | 90.6% | 0.946 (0.910 to 0.977) | 0.960 | 35 / 105 ms |
| 64 tokens, on | 96.9% | 0.981 (0.957 to 1.000) | 0.985 | 509 / 1079 ms |

The paired MRR gain is +0.028 (+0.005 to +0.054) at 256 tokens and +0.035 (+0.003 to +0.071) at 64. At 256 tokens 5 questions got better and none worse; at 64 tokens 7 got better and 3 worse. Quality passed the rule. Latency failed it (p95 limit 500 ms, median added limit 250 ms), so the default stays off. The earlier 560 ms figure was optimistic for this laptop; both numbers depend on passage length and CPU. The reranker score is now returned as `scores.rerank` in the search response when the reranker is on. Reconsider with a GPU, a smaller `EKA_RERANKER_TOP`, or a quantized or smaller cross-encoder. The corpus is still 13 short files by one author, so the gain is a measured result on this set, not a general claim.

## Options considered
| Option | Assessment |
|---|---|
| Off by default, switchable (chosen) | No cost for deployments that do not need it. The result is recorded, and the experiment can be repeated on a larger corpus. |
| On by default | Two questions out of 44 on a 13-chunk corpus is too small to justify about 560 ms on every search. |
| Not built | Leaves FR-22 unanswered and no evidence either way. |
| Hosted reranker API (Cohere, Voyage) | Sends passages to a third party and adds a cost per query. Possible behind the same port. |

## Consequences
The first rank improved in this run, but 2 of 44 on 13 chunks is within noise: the ceiling is 100% and the corpus is easy. Turning it on needs a larger evaluation set. A GPU, or a smaller `EKA_RERANKER_TOP`, would reduce the latency.
