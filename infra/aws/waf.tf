# A web ACL on the load balancer, in front of the edge's own checks: AWS managed rules for common
# attacks, known bad inputs and bad-reputation addresses, and a per-address rate rule that holds
# even when the edge's per-user limit fails open. Blocked requests are logged for 14 days.

locals {
  waf_managed_rules = {
    common        = { priority = 10, name = "AWSManagedRulesCommonRuleSet" }
    bad_inputs    = { priority = 20, name = "AWSManagedRulesKnownBadInputsRuleSet" }
    ip_reputation = { priority = 30, name = "AWSManagedRulesAmazonIpReputationList" }
  }
}

resource "aws_wafv2_web_acl" "edge" {
  name  = "${var.name}-edge"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  # Per source address, over a rolling five minutes. Not per user: that is the edge's job.
  rule {
    name     = "rate-per-address"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.waf_requests_per_address_per_5m
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name}-rate-per-address"
      sampled_requests_enabled   = true
    }
  }

  dynamic "rule" {
    for_each = local.waf_managed_rules
    content {
      name     = rule.key
      priority = rule.value.priority

      override_action {
        none {}
      }

      statement {
        managed_rule_group_statement {
          name        = rule.value.name
          vendor_name = "AWS"

          # Document uploads are larger than the common rule set's body limit; the edge and the
          # core enforce their own size limit (EKA_MAX_UPLOAD_MB), so this rule only counts.
          dynamic "rule_action_override" {
            for_each = rule.key == "common" ? ["SizeRestrictions_BODY"] : []
            content {
              name = rule_action_override.value
              action_to_use {
                count {}
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name}-${rule.key}"
        sampled_requests_enabled   = true
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name}-edge"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "edge" {
  resource_arn = aws_lb.edge.arn
  web_acl_arn  = aws_wafv2_web_acl.edge.arn
}

# WAF insists on this name prefix for its log groups.
resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-${var.name}"
  retention_in_days = 14
}

resource "aws_wafv2_web_acl_logging_configuration" "edge" {
  resource_arn            = aws_wafv2_web_acl.edge.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]

  # Only what was blocked or counted; allowed traffic is in the edge's own access log.
  logging_filter {
    default_behavior = "DROP"

    filter {
      behavior    = "KEEP"
      requirement = "MEETS_ANY"

      condition {
        action_condition {
          action = "BLOCK"
        }
      }

      condition {
        action_condition {
          action = "COUNT"
        }
      }
    }
  }

  redacted_fields {
    single_header {
      name = "authorization"
    }
  }
}
