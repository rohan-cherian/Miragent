variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region to deploy Miragent infrastructure into."
}

variable "environment" {
  type        = string
  default     = "production"
  description = "Deployment environment label (e.g. production, staging)."
}

variable "project_name" {
  type        = string
  default     = "miragent"
  description = "Short project identifier used as a prefix for all resource names."
}

variable "vpc_cidr" {
  type        = string
  default     = "10.0.0.0/16"
  description = "CIDR block for the VPC."
}

variable "availability_zones" {
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
  description = "List of Availability Zones to use for subnet placement."
}

variable "private_subnet_cidrs" {
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
  description = "CIDR blocks for private subnets (one per AZ)."
}

variable "public_subnet_cidrs" {
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24"]
  description = "CIDR blocks for public subnets (one per AZ)."
}

variable "ecs_task_cpu" {
  type        = number
  default     = 1024
  description = "API task CPU units (1024 = 1 vCPU)."
}

variable "ecs_task_memory" {
  type        = number
  default     = 2048
  description = "API task memory in MB."
}

variable "api_image_uri" {
  type        = string
  description = "Full ECR URI for the scout-api container image (e.g. 123456789.dkr.ecr.us-east-1.amazonaws.com/miragent-production-api:0.14.0)."
}

variable "worker_image_uri" {
  type        = string
  description = "Full ECR URI for the scout-worker container image."
}

variable "neo4j_password" {
  type        = string
  sensitive   = true
  description = "Password for the Neo4j database instance."
}

variable "scout_api_key" {
  type        = string
  sensitive   = true
  description = "API key used to authenticate requests to the Scout API."
}

variable "anthropic_api_key" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Anthropic API key for Claude model access. Leave empty to disable LLM features."
}

variable "domain_name" {
  type        = string
  default     = ""
  description = "Optional: Route53 domain name for an ALB DNS alias record. Leave empty to skip DNS setup."
}

variable "ecr_repository_name" {
  type        = string
  default     = "miragent"
  description = "Base name for the ECR repositories created for api and worker images."
}

variable "enable_nat_gateway" {
  type        = bool
  default     = true
  description = "Whether to provision a NAT Gateway so private subnets can reach the internet."
}

variable "tags" {
  type        = map(string)
  default     = {
    Project   = "miragent"
    ManagedBy = "terraform"
  }
  description = "Tags applied to all taggable AWS resources."
}
