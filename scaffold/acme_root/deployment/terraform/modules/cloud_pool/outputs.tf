output "launch_template_id" {
  description = "ACME_VM_LAUNCH_TEMPLATE."
  value       = aws_launch_template.vm.id
}

output "closed_security_group_id" {
  description = "ACME_VM_CLOSED_GROUP: reaches the gateway alone."
  value       = aws_security_group.closed.id
}

output "open_security_group_id" {
  description = "ACME_VM_OPEN_GROUP: adds open egress."
  value       = aws_security_group.open.id
}

output "subnet_ids" {
  description = "ACME_VM_SUBNETS, joined with commas."
  value       = var.subnet_ids
}

output "operate_policy_arn" {
  description = "The policy the runner's and the sweep's task roles take to hold the pool's VMs."
  value       = aws_iam_policy.operate.arn
}
