output "url" {
  value = "${var.certificate_arn == "" ? "http" : "https"}://${aws_lb.edge.dns_name}"
}

output "files_bucket" {
  value = aws_s3_bucket.files.bucket
}

output "log_group" {
  description = "CloudWatch log group of every container; OPS_AGENT_CLOUDWATCH_LOG_GROUP for the triage agent"
  value       = aws_cloudwatch_log_group.app.name
}

output "migrate_command" {
  description = "Run the database migration once after the first apply"
  value       = "aws ecs run-task --cluster ${aws_ecs_cluster.main.name} --launch-type FARGATE --task-definition ${aws_ecs_task_definition.migrate.family} --network-configuration awsvpcConfiguration={subnets=[${join(",", var.public_subnet_ids)}],securityGroups=[${aws_security_group.tasks.id}],assignPublicIp=ENABLED} --region ${var.region}"
}

output "deploy_role_arn" {
  description = "Set as the role-to-assume of aws-actions/configure-aws-credentials in the deploy workflow"
  value       = aws_iam_role.deploy.arn
}

output "ecr_core" {
  value = aws_ecr_repository.core.repository_url
}

output "ecr_edge" {
  value = aws_ecr_repository.edge.repository_url
}

output "waf_log_group" {
  value = aws_cloudwatch_log_group.waf.name
}
