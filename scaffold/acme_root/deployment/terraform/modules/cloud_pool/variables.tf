variable "environment" {
  description = "The environment's name, in every resource's."
  type        = string
}

variable "vpc_id" {
  description = "The network the VMs run in."
  type        = string
}

variable "subnet_ids" {
  description = "The private subnets a VM starts in, one picked per start."
  type        = list(string)
}

variable "gateway_security_group_id" {
  description = "The security group of the gateway's entry inside the network: the one place a closed VM reaches, on 443."
  type        = string
}

variable "image_id" {
  description = "The AMI every new VM boots: a Linux with Docker and the host program installed by deployment/vms/install.sh. A VM started from a session's snapshot boots that snapshot's image instead."
  type        = string
}

variable "instance_type" {
  description = "Every VM's size. The cloud pool asks for no other."
  type        = string
  default     = "m7g.large"
}

variable "disk_gb" {
  description = "Every VM's disk, which its session's snapshot keeps whole."
  type        = number
  default     = 64
}
