# GitHub Actions deploys with a short-lived token from GitHub's OIDC provider: no AWS access key
# is stored in GitHub. The role may be assumed only by workflows of one repository on one branch,
# and may only push the three images, register task definitions, update the three services, run the
# migration task and pass the task roles. It cannot change this infrastructure.

data "aws_partition" "current" {}

locals {
  github_oidc_host = "token.actions.githubusercontent.com"
  github_oidc_arn  = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${local.github_oidc_host}"
}

# One per account; set create_github_oidc_provider = false if the account already has it.
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://${local.github_oidc_host}"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/${var.github_branch}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name_prefix          = "${var.name}-deploy-"
  assume_role_policy   = data.aws_iam_policy_document.github_assume.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "deploy" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.core.arn, aws_ecr_repository.edge.arn, aws_ecr_repository.ops_agent.arn]
  }

  # These two calls are not resource-scoped in IAM.
  statement {
    actions   = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition", "ecs:DescribeTasks"]
    resources = ["*"]
  }

  statement {
    actions   = ["ecs:UpdateService", "ecs:DescribeServices"]
    resources = [aws_ecs_service.api.id, aws_ecs_service.worker.id, aws_ecs_service.ops_agent.id]
  }

  statement {
    actions   = ["ecs:RunTask"]
    resources = ["arn:${data.aws_partition.current.partition}:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:task-definition/${aws_ecs_task_definition.migrate.family}:*"]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }

  statement {
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.execution.arn, aws_iam_role.task.arn,
      aws_iam_role.ops_agent_execution.arn, aws_iam_role.ops_agent_task.arn,
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

# The two image repositories the workflow pushes to. Scanned on push; tags cannot be overwritten.
resource "aws_ecr_repository" "core" {
  name                 = "${var.name}-core"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = !var.keep_data_on_destroy

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "edge" {
  name                 = "${var.name}-edge"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = !var.keep_data_on_destroy

  image_scanning_configuration {
    scan_on_push = true
  }
}
