output "url" {
  value = "${var.certificate_arn == "" ? "http" : "https"}://${aws_lb.edge.dns_name}"
}

output "files_bucket" {
  value = aws_s3_bucket.files.bucket
}

output "migrate_command" {
  description = "Run the database migration once after the first apply"
  value       = "aws ecs run-task --cluster ${aws_ecs_cluster.main.name} --launch-type FARGATE --task-definition ${aws_ecs_task_definition.migrate.family} --network-configuration awsvpcConfiguration={subnets=[${join(",", var.public_subnet_ids)}],securityGroups=[${aws_security_group.tasks.id}],assignPublicIp=ENABLED} --region ${var.region}"
}
