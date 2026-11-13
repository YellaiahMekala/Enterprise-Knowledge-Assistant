# One small Redis for the edge's shared rate limit, so several edge tasks count a user together.
# TLS and an auth token: the URL the edge receives is rediss://:<token>@<host>:6379 from a secret.

resource "aws_security_group" "cache" {
  name_prefix = "${var.name}-cache-"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "cache_from_tasks" {
  security_group_id            = aws_security_group.cache.id
  referenced_security_group_id = aws_security_group.tasks.id
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

resource "aws_elasticache_subnet_group" "cache" {
  name       = "${var.name}-cache"
  subnet_ids = var.private_subnet_ids
}

resource "random_password" "cache_token" {
  length  = 48
  special = false
}

resource "aws_elasticache_replication_group" "cache" {
  replication_group_id       = "${var.name}-ratelimit"
  description                = "Shared rate-limit buckets for the edge"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.cache_node_type
  num_cache_clusters         = 1
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.cache.name
  security_group_ids         = [aws_security_group.cache.id]
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  auth_token                 = random_password.cache_token.result
  automatic_failover_enabled = false
  apply_immediately          = true
}

resource "aws_secretsmanager_secret" "cache_url" {
  name                    = "${var.name}/rate-limit-redis-url"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "cache_url" {
  secret_id     = aws_secretsmanager_secret.cache_url.id
  secret_string = "rediss://:${random_password.cache_token.result}@${aws_elasticache_replication_group.cache.primary_endpoint_address}:6379"
}
