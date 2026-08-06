variable "name_prefix" {
  type        = string
  description = "Prefix applied to all resource names within this module."
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC."
}

variable "availability_zones" {
  type        = list(string)
  description = "List of Availability Zones. One public and one private subnet is created per AZ."
}

variable "private_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for private subnets. Must match length of availability_zones."
}

variable "public_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for public subnets. Must match length of availability_zones."
}

variable "enable_nat_gateway" {
  type        = bool
  default     = true
  description = "Whether to provision a NAT Gateway so that private subnets can reach the internet."
}
