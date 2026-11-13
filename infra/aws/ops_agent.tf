# P14: the triage agent as its own Fargate service. It has no inbound port at all: it polls the
# alarm queue, reads health from the api tasks through a private DNS name, searches CloudWatch
# Logs, and sends its report by SMTP. Read-only on every system it looks at.

resource "aws_service_discovery_private_dns_namespace" "internal" {
  name = "${var.name}.internal"
  vpc  = var.vpc_id
}

# Each api task registers its address as api.<name>.internal.
resource "aws_service_discovery_service" "api" {
  name = "api"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.internal.id
    routing_policy = "MULTIVALUE"

    dns_records {
      type = "A"
      ttl  = 10
    }
  }

  health_check_custom_config {}
}

resource "aws_security_group" "ops_agent" {
  name_prefix = "${var.name}-ops-agent-"
  vpc_id      = var.vpc_id
}

# Outbound only: the model API, SMTP, AWS APIs, and the api tasks' health endpoints.
resource "aws_vpc_security_group_egress_rule" "ops_agent_out" {
  security_group_id = aws_security_group.ops_agent.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# The agent may reach the core's health (8000) and the edge's management port (8081), nothing else.
resource "aws_vpc_security_group_ingress_rule" "tasks_from_ops_agent" {
  for_each                     = toset(["8000", "8081"])
  security_group_id            = aws_security_group.tasks.id
  referenced_security_group_id = aws_security_group.ops_agent.id
  from_port                    = tonumber(each.value)
  to_port                      = tonumber(each.value)
  ip_protocol                  = "tcp"
}

resource "random_password" "ops_webhook" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "ops_webhook" {
  name                    = "${var.name}/ops-agent-webhook-token"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "ops_webhook" {
  secret_id     = aws_secretsmanager_secret.ops_webhook.id
  secret_string = random_password.ops_webhook.result
}

# Values Terraform must not know: created with a placeholder, set by the owner after apply with
#   aws secretsmanager put-secret-value --secret-id <name> --secret-string '...'
# and never overwritten by a later apply. With the placeholder key the model call fails and the
# agent reports from the runbook alone; with the placeholder password the email fails and
# EkaTriageReportFailed fires.
resource "aws_secretsmanager_secret" "ops_manual" {
  for_each                = toset(["ops-agent-model-api-key", "ops-agent-smtp-password"])
  name                    = "${var.name}/${each.key}"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "ops_manual" {
  for_each      = aws_secretsmanager_secret.ops_manual
  secret_id     = each.value.id
  secret_string = "set-me"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_ecr_repository" "ops_agent" {
  name                 = "${var.name}-ops-agent"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = !var.keep_data_on_destroy

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_iam_role" "ops_agent_execution" {
  name_prefix        = "${var.name}-ops-exec-"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "ops_agent_execution" {
  role       = aws_iam_role.ops_agent_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ops_agent_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [aws_secretsmanager_secret.ops_webhook.arn],
      [for s in aws_secretsmanager_secret.ops_manual : s.arn],
    )
  }
}

resource "aws_iam_role_policy" "ops_agent_execution_secrets" {
  role   = aws_iam_role.ops_agent_execution.id
  policy = data.aws_iam_policy_document.ops_agent_secrets.json
}

# What the agent itself may do: read and delete messages on its queue, read the log group.
resource "aws_iam_role" "ops_agent_task" {
  name_prefix        = "${var.name}-ops-task-"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "ops_agent_task" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.alarms.arn]
  }

  # The searchLogs tool (ADR-035).
  statement {
    actions   = ["logs:FilterLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ops_agent_task" {
  role   = aws_iam_role.ops_agent_task.id
  policy = data.aws_iam_policy_document.ops_agent_task.json
}

resource "aws_ecs_task_definition" "ops_agent" {
  family                   = "${var.name}-ops-agent"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ops_agent_execution.arn
  task_role_arn            = aws_iam_role.ops_agent_task.arn

  container_definitions = jsonencode([
    {
      name      = "ops-agent"
      image     = var.ops_agent_image
      essential = true
      environment = [
        { name = "JAVA_TOOL_OPTIONS", value = "-XX:MaxRAMPercentage=70" },
        { name = "OPS_AGENT_ALARM_QUEUE_URL", value = aws_sqs_queue.alarms.url },
        { name = "OPS_AGENT_CLOUDWATCH_LOG_GROUP", value = aws_cloudwatch_log_group.app.name },
        { name = "OPS_AGENT_PROMETHEUS_URL", value = "" },
        { name = "OPS_AGENT_CORE_URL", value = "http://api.${aws_service_discovery_private_dns_namespace.internal.name}:8000" },
        { name = "OPS_AGENT_EDGE_MANAGEMENT_URL", value = "http://api.${aws_service_discovery_private_dns_namespace.internal.name}:8081" },
        { name = "OPS_AGENT_RUNBOOK_FILE", value = "/app/runbooks.md" },
        { name = "AWS_REGION", value = var.region },
        { name = "EKA_CHAT_MODEL", value = var.ops_agent_model },
        { name = "EKA_ALERT_EMAIL_TO", value = var.alert_email },
        { name = "EKA_ALERT_EMAIL_FROM", value = var.alert_email_from },
        { name = "EKA_ALERT_SMTP_HOST", value = var.smtp_host },
        { name = "EKA_ALERT_SMTP_PORT", value = tostring(var.smtp_port) },
        { name = "EKA_ALERT_SMTP_USER", value = var.smtp_user },
      ]
      secrets = [
        { name = "OPS_AGENT_WEBHOOK_TOKEN", valueFrom = aws_secretsmanager_secret.ops_webhook.arn },
        { name = "EKA_CHAT_API_KEY", valueFrom = aws_secretsmanager_secret.ops_manual["ops-agent-model-api-key"].arn },
        { name = "EKA_ALERT_SMTP_PASSWORD", valueFrom = aws_secretsmanager_secret.ops_manual["ops-agent-smtp-password"].arn },
      ]
      logConfiguration = local.log
    },
  ])

  depends_on = [aws_secretsmanager_secret_version.ops_manual]
}

resource "aws_ecs_service" "ops_agent" {
  name            = "${var.name}-ops-agent"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ops_agent.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.ops_agent.id]
    assign_public_ip = true
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}
