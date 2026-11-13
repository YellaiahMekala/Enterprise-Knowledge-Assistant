# AWS deployment (Terraform)

Status: **written and validated (`terraform validate`), never applied.** Nothing here has run against an AWS account, so treat the details (service limits, Bedrock model access, the pgvector version RDS offers) as unverified until a real apply.

## What it builds
| Piece | Choice |
|---|---|
| Compute | ECS Fargate. One service runs the edge and the core as two containers in one task (they talk over `localhost`, so the core is never reachable from outside the task); one service runs the worker; a one-off task runs the migration |
| Database | RDS PostgreSQL 17, encrypted, in private subnets, reachable only from the tasks. The first migration enables pgvector |
| Files | S3 bucket, encrypted, public access blocked, task role limited to that bucket |
| Model | Amazon Bedrock through the task role (`bedrock:InvokeModel*`); no API key or AWS key is stored anywhere |
| Entry | Application load balancer in front of the edge, limited to `allowed_cidrs`; HTTPS when `certificate_arn` is set |
| Secrets | Database URL and pseudonym secret in Secrets Manager, injected into the containers at start |
| Identity | An external OIDC provider (variables `oidc_issuer`, `oidc_jwk_set_uri`); this stack does not create one |

## Added in P13 (code only, not applied)
| Piece | File | Notes |
|---|---|---|
| Autoscaling | `autoscaling.tf` | api service 2 to 4 tasks on CPU 60% and requests per task; worker stays at 1 |
| Shared rate limit | `cache.tf` + edge `RedisRateLimiter` | ElastiCache Redis 7.1 with TLS and an auth token in a secret; the edge fails open if Redis is down, the WAF rate rule still applies |
| WAF | `waf.tf` | per-address rate rule, three AWS managed rule groups, upload-size rule in count mode, blocked requests logged (authorization header redacted) |
| Deploy role | `deploy_role.tf` | GitHub OIDC, one repository and one branch, ECR push, ECS update and migration run, pass the two task roles; cannot change infrastructure. Plus two immutable ECR repositories |

New required variable: `github_repository`. Costs rise: two tasks minimum, an ElastiCache node and the WAF (roughly 5 USD plus per-request fees a month for the ACL and rules). Re-estimate before applying.

## Use
```bash
cp terraform.tfvars.example terraform.tfvars    # fill in; the file is git-ignored
terraform init -backend-config=...              # use an encrypted remote backend: the state holds secrets
terraform plan
terraform apply                                  # asks first; this creates billable resources
# build and push the two images to ECR first, and put their URIs in terraform.tfvars
terraform output migrate_command                 # run it once; then the service can start serving
```
Deploy, record the evidence (screenshots, a request log), then `terraform destroy`. With `keep_data_on_destroy = false` (the default) destroy removes the database and the bucket contents.

## Cost
A rough estimate, not a quote: Fargate for 2 vCPU and 4 GB in total, a `db.t4g.micro` RDS instance, an application load balancer and logs come to somewhere around 80 to 120 US dollars a month if left running, and about 3 to 4 dollars a day. Bedrock calls are extra and depend on the model. Check the AWS pricing calculator for your region before applying.

## Logs
Every container writes to the log group `/<name>` (output `log_group`), one stream per container named `eka/<container>/<task id>`. The task role may read that group (`logs:FilterLogEvents`, `logs:DescribeLogStreams`), so the triage agent's CloudWatch adapter works with `OPS_AGENT_CLOUDWATCH_LOG_GROUP=$(terraform output -raw log_group)`. The agent itself is not deployed by this stack; the adapter was tested against LocalStack only.

## Known gaps
- The edge generates its signing key at start (`EKA_EDGE_EPHEMERAL_KEY=true`), so a restart changes the key. The core refetches the key set on an unknown key id, but that path was only tested locally.
- Tasks run in public subnets with public IPs to avoid a NAT gateway. A production setup would use private subnets with a NAT gateway or VPC endpoints.
- No alarms wired to the alert rules, and no deploy workflow yet: the role exists, the workflow that assumes it does not.
- The WAF, autoscaling, ElastiCache and OIDC role are validated only; none has run in an account. WAF rule behaviour (false positives on uploads, the rate rule's 5-minute window) needs a real request test.
