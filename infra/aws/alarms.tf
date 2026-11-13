# CloudWatch alarms for the alert rules that have an AWS equivalent (P13). Alarm names match the
# rules in monitoring/alerts.yml, so the triage agent finds the same runbook sections; the
# description starts with the severity. Alarms go to SNS, SNS to an SQS queue, and the agent polls
# the queue (ops_agent.tf). The watchdog alarms go to email instead, so they arrive when the agent
# is down, as in alertmanager.yml.
#
# Not mapped: EkaSearchSlow (the load balancer has no per-route latency), EkaEdgeCircuitOpen and
# EkaLlmFailoverBurst (their metrics are Prometheus-only and no Prometheus runs on AWS).

resource "aws_sns_topic" "alarms" {
  name              = "${var.name}-alarms"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sqs_queue" "alarms_dead" {
  name                      = "${var.name}-alarms-dead"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "alarms" {
  name                       = "${var.name}-alarms"
  message_retention_seconds  = 86400
  visibility_timeout_seconds = 60
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.alarms_dead.arn
    maxReceiveCount     = 5
  })
}

data "aws_iam_policy_document" "alarms_queue" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.alarms.arn]

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_sns_topic.alarms.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "alarms" {
  queue_url = aws_sqs_queue.alarms.id
  policy    = data.aws_iam_policy_document.alarms_queue.json
}

resource "aws_sns_topic_subscription" "alarms_to_queue" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.alarms.arn
}

# Straight to a person. Email subscriptions must be confirmed from the inbox after apply.
resource "aws_sns_topic" "watchdog" {
  name              = "${var.name}-watchdog"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "watchdog_email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.watchdog.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# alerts.yml: 5xx ratio above 14.4 x 0.5% for 5 minutes, with at least 0.1 requests a second.
resource "aws_cloudwatch_metric_alarm" "high_error_rate" {
  alarm_name          = "EkaHighErrorRate"
  alarm_description   = "[page] More than 7.2% of requests through the load balancer are failing with 5xx"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0.072
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  metric_query {
    id          = "ratio"
    expression  = "IF(requests > 30, errors / requests, 0)"
    label       = "5xx ratio"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_Target_5XX_Count"
      dimensions  = { LoadBalancer = aws_lb.edge.arn_suffix }
      period      = 300
      stat        = "Sum"
    }
  }

  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "RequestCount"
      dimensions  = { LoadBalancer = aws_lb.edge.arn_suffix }
      period      = 300
      stat        = "Sum"
    }
  }
}

# alerts.yml: a scrape target down for 2 minutes. Here: no healthy edge task for 2 minutes.
resource "aws_cloudwatch_metric_alarm" "target_down" {
  alarm_name          = "EkaTargetDown"
  alarm_description   = "[page] The load balancer has no healthy edge task"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = { LoadBalancer = aws_lb.edge.arn_suffix, TargetGroup = aws_lb_target_group.edge.arn_suffix }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 2
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

# alerts.yml EkaTriageReportFailed: the agent logs this line when a report could not be sent.
resource "aws_cloudwatch_log_metric_filter" "report_failed" {
  name           = "${var.name}-triage-report-failed"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "\"EkaTriageReportFailed will fire\""

  metric_transformation {
    name          = "TriageReportsFailed"
    namespace     = "EKA"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "report_failed" {
  alarm_name          = "EkaTriageReportFailed"
  alarm_description   = "[page] The triage agent accepted an alarm but could not send its report"
  namespace           = "EKA"
  metric_name         = "TriageReportsFailed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.watchdog.arn]
}

# alerts.yml EkaAlertDeliveryFailing: alarms are not reaching the agent. An alarm waiting in the
# queue for 15 minutes means the agent is not polling; anything in the dead-letter queue means a
# message failed five times.
resource "aws_cloudwatch_metric_alarm" "delivery_stuck" {
  alarm_name          = "EkaAlertDeliveryFailing"
  alarm_description   = "[page] An alarm has waited 15 minutes for the triage agent; check the ops-agent service"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = aws_sqs_queue.alarms.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 900
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.watchdog.arn]
}

resource "aws_cloudwatch_metric_alarm" "delivery_dead_letters" {
  alarm_name          = "EkaAlertDeliveryDeadLetters"
  alarm_description   = "[page] Alarm messages failed five times and were moved to the dead-letter queue"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.alarms_dead.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.watchdog.arn]
}
