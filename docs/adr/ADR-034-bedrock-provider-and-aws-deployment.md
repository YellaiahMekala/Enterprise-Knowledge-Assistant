# ADR-034: Bedrock chat provider and an AWS deployment shape

| | |
|---|---|
| Status | Accepted (built and unit-tested; not run against AWS) |
| Date | 2026-11-08 |
| Decision owner | Maintainer |
| Review trigger | The first real Bedrock call or `terraform apply`, whichever comes first; a cost above the estimate in `infra/aws/README.md`. |
| Related | ADR-006, ADR-013, ADR-022 |

## Context
The chat model sits behind a port with a fake and an OpenAI-compatible adapter. Many enterprise environments cannot send data to a third-party API but can use Bedrock inside their own AWS account. Files already sit behind a storage port with an S3 adapter.

## Decision
1. **A Bedrock adapter** on the Converse API (`EKA_CHAT_PROVIDER=bedrock`, `EKA_CHAT_MODEL` is the model id). Converse has one request shape for every Bedrock model, so changing the model is a setting. Credentials come from the AWS credential chain, so there is no key in this project's settings.
2. **An AWS deployment as Terraform** in `infra/aws`: ECS Fargate with the edge and the core in one task over `localhost`, a worker service and a one-off migration task, RDS PostgreSQL, S3, Secrets Manager, an application load balancer, and a task role limited to the bucket and to Bedrock invocation.

## Options considered
| Option | Assessment |
|---|---|
| Converse API (chosen) | One shape for all models, supports streaming. |
| `InvokeModel` with per-model JSON | Each model family has a different body. More code and more branches. |
| Spring AI or LangChain4j Bedrock in the edge | Moves model calls into the edge, which is meant to stay thin. |
| ECS Fargate (chosen) | No servers to patch, simple for three small services. |
| EKS | More to show and more to run for three services. Revisit if there are many services. |
| Lambda | Streaming answers and a long-lived worker fit it poorly. |
| Edge and core in one task (chosen) | No service discovery, and the core is not reachable from outside the task. Cost: they scale together. |
| Separate services with Cloud Map | Scales separately; more infrastructure to explain and run. |

## Consequences
- The adapter is tested against a stub client (request shape, streaming, early close, error mapping), not against Bedrock. Model access must be enabled in the AWS account, and the first real call may show differences (inference profile ids, regional availability).
- The Terraform is validated but never applied. The estimate in its README is rough.
- Generated secrets live in Terraform state, so the state must be in an encrypted remote backend.
