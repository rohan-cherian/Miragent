terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = merge(var.tags, {
    Environment = var.environment
  })
}

# ──────────────────────────────────────────────────────────────
# Networking module
# ──────────────────────────────────────────────────────────────
module "networking" {
  source = "./modules/networking"

  name_prefix          = local.name_prefix
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  private_subnet_cidrs = var.private_subnet_cidrs
  public_subnet_cidrs  = var.public_subnet_cidrs
  enable_nat_gateway   = var.enable_nat_gateway
}

# ──────────────────────────────────────────────────────────────
# ECS module
# ──────────────────────────────────────────────────────────────
module "ecs" {
  source = "./modules/ecs"

  cluster_name      = "${local.name_prefix}-cluster"
  name_prefix       = local.name_prefix
  api_image_uri     = var.api_image_uri
  worker_image_uri  = var.worker_image_uri

  private_subnet_ids = module.networking.private_subnet_ids
  public_subnet_ids  = module.networking.public_subnet_ids
  vpc_id             = module.networking.vpc_id

  task_cpu          = var.ecs_task_cpu
  task_memory       = var.ecs_task_memory

  neo4j_password    = var.neo4j_password
  scout_api_key     = var.scout_api_key
  anthropic_api_key = var.anthropic_api_key

  api_secret_arn    = aws_secretsmanager_secret.scout_api_key.arn
}

# ──────────────────────────────────────────────────────────────
# ECR repositories (inline)
# ──────────────────────────────────────────────────────────────
resource "aws_ecr_repository" "api" {
  name                 = "${local.name_prefix}-api"
  image_tag_mutability = "MUTABLE"

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

resource "aws_ecr_repository" "worker" {
  name                 = "${local.name_prefix}-worker"
  image_tag_mutability = "MUTABLE"

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

# ──────────────────────────────────────────────────────────────
# Secrets Manager (inline)
# ──────────────────────────────────────────────────────────────
resource "aws_secretsmanager_secret" "scout_api_key" {
  name                    = "${local.name_prefix}/scout-api-key"
  description             = "Scout API key for Miragent ${var.environment}"
  recovery_window_in_days = 7

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "scout_api_key" {
  secret_id     = aws_secretsmanager_secret.scout_api_key.id
  secret_string = var.scout_api_key
}

resource "aws_secretsmanager_secret" "neo4j_password" {
  name                    = "${local.name_prefix}/neo4j-password"
  description             = "Neo4j password for Miragent ${var.environment}"
  recovery_window_in_days = 7

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "neo4j_password" {
  secret_id     = aws_secretsmanager_secret.neo4j_password.id
  secret_string = var.neo4j_password
}
