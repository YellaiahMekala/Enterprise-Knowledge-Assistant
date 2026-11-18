# LocalStack harness for the alarm queue path (PQ1.2.5). The real resources come from
# ../alarms.tf (the SNS topic, both queues, the queue policy and the subscription are copied by run_tf.sh at run time, so
# this cannot drift); the alarm below stands in for the ELB-based ones, which need a load balancer.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

variable "name" {
  type    = string
  default = "eka"
}

variable "endpoint" {
  type    = string
  default = "http://host.docker.internal:4567"
}

provider "aws" {
  region                      = "eu-west-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  endpoints {
    sns        = var.endpoint
    sqs        = var.endpoint
    cloudwatch = var.endpoint
  }
}

resource "aws_cloudwatch_metric_alarm" "test_high_error_rate" {
  alarm_name          = "EkaHighErrorRate"
  alarm_description   = "[page] More than 7.2% of requests through the load balancer are failing with 5xx"
  namespace           = "EKA/Test"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0.072
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

output "alarm_queue_url" {
  value = aws_sqs_queue.alarms.url
}

output "dead_letter_queue_url" {
  value = aws_sqs_queue.alarms_dead.url
}

output "topic_arn" {
  value = aws_sns_topic.alarms.arn
}
