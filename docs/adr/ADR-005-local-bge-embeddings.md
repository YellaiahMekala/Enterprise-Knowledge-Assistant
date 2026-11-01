# ADR-005: Local BGE-small embeddings through fastembed

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Quality is insufficient on the evaluation set, non-English support is needed, or embedding throughput becomes the bottleneck. |
| Related | FR-16, ADR-006 |

## Context
Evaluation must run offline in CI and ingestion should have no per-call cost. fastembed's model metadata lists `BAAI/bge-small-en-v1.5` at 384 dimensions with a 512-token input limit.

## Decision
`BAAI/bge-small-en-v1.5` on the ONNX runtime, in-process in `api` and `worker`. `embedding_model` is stored on every chunk.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Local BGE-small (chosen) | No cost, no key, offline CI. English only; 512-token cap constrains chunk size; a model change needs re-embedding. |
| OpenAI embeddings default | Higher quality ceiling, no CPU load. Cost per CI run, key in CI. Kept behind the `Embedder` port. |
| Ollama | Local and private. Slower, heavier operationally. Rejected for default. |

## Consequences
Vectors are not comparable across models; a re-embedding job is required on model change.
