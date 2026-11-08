terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # The state holds generated secrets (database password, pseudonym secret). Use an encrypted
  # remote backend (S3 with a KMS key and locking) before applying this for real:
  #   terraform init -backend-config=...
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project = "enterprise-knowledge-assistant"
      managed = "terraform"
    }
  }
}
