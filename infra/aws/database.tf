resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_security_group" "db" {
  name_prefix = "${var.name}-db-"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_tasks" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.tasks.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_db_subnet_group" "db" {
  name       = "${var.name}-db"
  subnet_ids = var.private_subnet_ids
}

# PostgreSQL 17 on RDS ships pgvector; the first migration runs CREATE EXTENSION vector.
resource "aws_db_instance" "db" {
  identifier                = "${var.name}-db"
  engine                    = "postgres"
  engine_version            = "17"
  instance_class            = var.db_instance_class
  allocated_storage         = 20
  storage_encrypted         = true
  db_name                   = "eka"
  username                  = "eka"
  password                  = random_password.db.result
  db_subnet_group_name      = aws_db_subnet_group.db.name
  vpc_security_group_ids    = [aws_security_group.db.id]
  publicly_accessible       = false
  backup_retention_period   = 7
  deletion_protection       = var.keep_data_on_destroy
  skip_final_snapshot       = !var.keep_data_on_destroy
  final_snapshot_identifier = var.keep_data_on_destroy ? "${var.name}-final" : null
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.name}/database-url"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql+psycopg://eka:${random_password.db.result}@${aws_db_instance.db.address}:5432/eka"
}

resource "random_password" "pseudonym" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "pseudonym" {
  name                    = "${var.name}/pseudonym-secret"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "pseudonym" {
  secret_id     = aws_secretsmanager_secret.pseudonym.id
  secret_string = random_password.pseudonym.result
}
