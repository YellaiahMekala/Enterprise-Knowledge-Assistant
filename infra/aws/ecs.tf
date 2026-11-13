locals {
  core_env = [
    { name = "EKA_ENVIRONMENT", value = "production" },
    { name = "EKA_AUTH_MODE", value = "gateway" },
    { name = "EKA_GATEWAY_JWKS_URL", value = "http://127.0.0.1:8081/actuator/jwks" },
    { name = "EKA_STORAGE_BACKEND", value = "s3" },
    { name = "EKA_S3_BUCKET", value = aws_s3_bucket.files.bucket },
    { name = "EKA_S3_REGION", value = var.region },
    { name = "EKA_CHAT_PROVIDER", value = "bedrock" },
    { name = "EKA_CHAT_MODEL", value = var.chat_model },
    { name = "EKA_BEDROCK_REGION", value = var.region },
  ]

  core_secrets = [
    { name = "EKA_DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
  ]

  log = {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.app.name
      awslogs-region        = var.region
      awslogs-stream-prefix = "eka"
    }
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.name}"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "main" {
  name = var.name
}

# The edge and the core share one task, so they talk over localhost and the core is never
# reachable from outside the task.
resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name             = "core"
      image            = var.core_image
      essential        = true
      portMappings     = [{ containerPort = 8000 }]
      environment      = local.core_env
      secrets          = local.core_secrets
      logConfiguration = local.log
    },
    {
      name         = "edge"
      image        = var.edge_image
      essential    = true
      portMappings = [{ containerPort = 8080 }, { containerPort = 8081 }]
      environment = [
        { name = "EKA_EDGE_CORE_URL", value = "http://127.0.0.1:8000" },
        { name = "EKA_EDGE_OIDC_ISSUER", value = var.oidc_issuer },
        { name = "EKA_EDGE_OIDC_JWK_SET_URI", value = var.oidc_jwk_set_uri },
        { name = "EKA_EDGE_OIDC_AUDIENCE", value = var.oidc_audience },
        { name = "EKA_EDGE_EPHEMERAL_KEY", value = "true" },
      ]
      secrets = [
        { name = "EKA_EDGE_PSEUDONYM_SECRET", valueFrom = aws_secretsmanager_secret.pseudonym.arn },
        { name = "EKA_EDGE_RATE_LIMIT_REDIS_URL", valueFrom = aws_secretsmanager_secret.cache_url.arn },
      ]
      logConfiguration = local.log
    },
  ])
}

resource "aws_ecs_service" "api" {
  name            = "${var.name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_min_tasks
  launch_type     = "FARGATE"

  # Autoscaling owns the count after the first apply; the deploy role owns the task definition.
  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.edge.arn
    container_name   = "edge"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.http, aws_lb_listener.https]
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name             = "worker"
      image            = var.core_image
      essential        = true
      command          = ["python", "-m", "eka.worker"]
      environment      = local.core_env
      secrets          = local.core_secrets
      logConfiguration = local.log
    },
  ])
}

resource "aws_ecs_service" "worker" {
  name            = "${var.name}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }
}

# Run once after every deploy that changes the schema: see the output migrate_command.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name             = "migrate"
      image            = var.core_image
      essential        = true
      command          = ["alembic", "upgrade", "head"]
      environment      = local.core_env
      secrets          = local.core_secrets
      logConfiguration = local.log
    },
  ])
}
