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
