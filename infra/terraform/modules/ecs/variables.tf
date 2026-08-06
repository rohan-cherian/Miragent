variable "cluster_name" {
  type        = string
  description = "Name of the ECS cluster to create."
}

variable "name_prefix" {
  type        = string
  description = "Prefix applied to all resource names within this module."
}

variable "api_image_uri" {
  type        = string
  description = "Full ECR URI (including tag) for the scout-api container image."
}

variable "worker_image_uri" {
  type        = string
  description = "Full ECR URI (including tag) for the scout-worker container image."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "IDs of private subnets where ECS tasks will be placed."
}

variable "public_subnet_ids" {
  type        = list(string)
  default     = []
  description = "IDs of public subnets for the Application Load Balancer. Required if deploying an internet-facing ALB."
}

variable "vpc_id" {
  type        = string
  description = "ID of the VPC in which to create security groups and the ALB."
}

variable "task_cpu" {
  type        = number
  description = "CPU units for the API Fargate task (1024 = 1 vCPU)."
}

variable "task_memory" {
  type        = number
  description = "Memory (MB) for the API Fargate task."
}

variable "scout_api_key" {
  type        = string
  sensitive   = true
  description = "Scout API key passed as an environment secret."
}

variable "neo4j_password" {
  type        = string
  sensitive   = true
  description = "Neo4j database password passed as an environment secret."
}

variable "anthropic_api_key" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Anthropic API key passed as an environment secret. Leave empty to omit."
}

variable "api_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret holding the Scout API key (used by ECS task execution role)."
}
