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

## Known gaps
- The edge generates its signing key at start (`EKA_EDGE_EPHEMERAL_KEY=true`), so a restart changes the key. The core refetches the key set on an unknown key id, but that path was only tested locally.
- One task and no autoscaling. The rate limiter is in memory, so more than one edge task would multiply the limits.
- Tasks run in public subnets with public IPs to avoid a NAT gateway. A production setup would use private subnets with a NAT gateway or VPC endpoints.
- No WAF, no alarms wired to the alert rules, no CI deploy (an OIDC-based GitHub Actions role is the next step, so no keys are stored in GitHub).
