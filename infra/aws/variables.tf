variable "region" {
  type    = string
  default = "eu-west-1"
}

variable "name" {
  description = "Prefix for resource names"
  type        = string
  default     = "eka"
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  description = "At least two, in different zones: the load balancer and the tasks. Tasks get a public IP so they can reach Bedrock, the identity provider and the model download without a NAT gateway."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "At least two, in different zones: the database"
  type        = list(string)
}

variable "allowed_cidrs" {
  description = "Who may reach the load balancer. No default on purpose: choose it."
  type        = list(string)

  validation {
    condition     = length(var.allowed_cidrs) > 0
    error_message = "Set allowed_cidrs, for example your own address as a /32."
  }
}

variable "certificate_arn" {
  description = "ACM certificate for HTTPS. Empty means plain HTTP, for a short demo only."
  type        = string
  default     = ""
}

variable "core_image" {
  description = "The core image, which also runs the worker and the migration (for example an ECR URI with a tag)"
  type        = string
}

variable "edge_image" {
  type = string
}

variable "oidc_issuer" {
  type = string
}

variable "oidc_jwk_set_uri" {
  type = string
}

variable "oidc_audience" {
  type    = string
  default = "eka-api"
}

variable "chat_model" {
  description = "Bedrock model id, for example anthropic.claude-3-haiku-20240307-v1:0"
  type        = string
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "keep_data_on_destroy" {
  description = "true keeps a final database snapshot and blocks deletion; false lets terraform destroy remove everything"
  type        = bool
  default     = false
}

variable "api_min_tasks" {
  description = "Fewest api tasks (edge + core). Two keeps one task up during a deploy or a task failure."
  type        = number
  default     = 2
}

variable "api_max_tasks" {
  type    = number
  default = 4
}

variable "api_requests_per_task_per_minute" {
  description = "Scale out when the load balancer sends more than this many requests a minute to each task"
  type        = number
  default     = 600
}

variable "cache_node_type" {
  description = "ElastiCache node for the shared rate limit"
  type        = string
  default     = "cache.t4g.micro"
}

variable "waf_requests_per_address_per_5m" {
  description = "WAF blocks an address that sends more than this many requests in five minutes (minimum 10)"
  type        = number
  default     = 2000
}

variable "github_repository" {
  description = "owner/name of the repository whose workflows may deploy, for example my-org/enterprise-knowledge-assistant"
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use the form owner/name."
  }
}

variable "github_branch" {
  description = "The only branch whose workflows may assume the deploy role"
  type        = string
  default     = "main"
}

variable "create_github_oidc_provider" {
  description = "false if this AWS account already has GitHub's OIDC provider (only one is allowed per account)"
  type        = bool
  default     = true
}

variable "ops_agent_image" {
  description = "The triage agent image built with ops-agent/Dockerfile.aws (runbooks included)"
  type        = string
}

variable "ops_agent_model" {
  type    = string
  default = "gpt-4o-mini"
}

variable "alert_email" {
  description = "Who receives triage reports and the watchdog alarms. Empty: no email subscription"
  type        = string
  default     = ""
}

variable "alert_email_from" {
  type    = string
  default = ""
}

variable "smtp_host" {
  description = "For example email-smtp.eu-west-1.amazonaws.com (SES) or another provider"
  type        = string
  default     = ""
}

variable "smtp_port" {
  type    = number
  default = 587
}

variable "smtp_user" {
  type    = string
  default = ""
}
