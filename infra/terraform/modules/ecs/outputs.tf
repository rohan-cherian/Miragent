output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer."
  value       = aws_lb.main.dns_name
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster."
  value       = aws_ecs_cluster.main.name
}

output "api_service_name" {
  description = "Name of the ECS service running the Scout API."
  value       = aws_ecs_service.api.name
}

output "ecs_tasks_security_group_id" {
  description = "ID of the security group attached to ECS task network interfaces."
  value       = aws_security_group.ecs_tasks.id
}
