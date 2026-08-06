output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer fronting the Scout API."
  value       = module.ecs.alb_dns_name
}

output "ecr_api_repository_url" {
  description = "ECR repository URL for the scout-api image."
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_worker_repository_url" {
  description = "ECR repository URL for the scout-worker image."
  value       = aws_ecr_repository.worker.repository_url
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster running Miragent services."
  value       = module.ecs.ecs_cluster_name
}

output "vpc_id" {
  description = "ID of the VPC created for Miragent."
  value       = module.networking.vpc_id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets where ECS tasks run."
  value       = module.networking.private_subnet_ids
}

output "api_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the Scout API key."
  value       = aws_secretsmanager_secret.scout_api_key.arn
}
