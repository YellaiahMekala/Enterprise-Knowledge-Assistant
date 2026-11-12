# ADR-036: Citation grounding check and a refusal gate of 0.50

| | |
|---|---|
| Status | Accepted (built; checked with the offline model; a real-model rerun is task P10-A) |
| Date | 2026-11-11 |
| Decision owner | Maintainer |
| Review trigger | A real-model rerun that shows wrong rejections or more unanswerable questions answered; a new embedding model or query prefix (the cosine scale moves). |
| Related | ADR-006, ADR-031 |

## Context
The first real-model run (44 questions, `gpt-4o-mini`) found two defects. q31 was refused because its best passage scored cosine 0.526 against a gate of 0.55, so the model was never asked. q29 was answered correctly but cited the wrong passage: the model wrote `[2]`, and the check only tested that passage 2 had been sent.

## Decision
1. **Gate 0.55 to 0.50.** The sweep on both evaluation sets shows 0.50 refuses no answerable question. The cost is that the gate stops 2 of 10 unanswerable questions instead of 3; the model's own `INSUFFICIENT_EVIDENCE` reply has to catch the rest.
2. **A grounding check** (`services/grounding.py`). A citation is rejected when the cited passages cover less than half of the sentence's content words and another sent passage covers at least half and twice as many. In verified mode the model is asked once more; otherwise the answer is withheld as unverified.

## Options considered
| Option | Assessment |
|---|---|
| Word-overlap grounding (chosen) | Deterministic, no extra model call, no cost; catches clear mistakes only |
| A second model call to judge support (LLM as judge) | Catches more, costs a call per answer and can be wrong itself; a possible later evaluation tool, not a runtime gate |
| NLI or cross-encoder support scoring | Heavier dependency and latency for a small gain at this corpus size |
| Gate on sparse evidence as well as cosine | Not needed once 0.50 passes the sweep; revisit if the corpus grows |
| Leave the gate and fix the prompt | Does not help q31: the model was never called |

## Consequences
- A paraphrase that matches no passage well is left alone. The check misses a wrong citation that shares words with the wrong passage.
- The cosine gate is a trade-off: lowering it answers more questions and refuses fewer unanswerable ones. Thresholds must be re-swept after any embedding change.
- The check was verified with an extractive offline model. How often it catches or wrongly rejects a real model's paraphrases is unmeasured until P10-A.
