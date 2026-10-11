# A machine of the cloud pool reaches nothing but the gateway, and what its
# session's policy opened; nothing reaches in; it holds no role; its disk is
# encrypted under the pool's key; and the platform's hold on the machines
# starts them from the template alone and passes no role.
# Runs offline: `terraform test` in this folder.

mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_region" {
    defaults = { region = "us-west-2" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:us-west-2:123456789012:key/disks" }
  }
}

variables {
  environment               = "staging"
  vpc_id                    = "vpc-0pool"
  subnet_ids                = ["subnet-0a", "subnet-0b"]
  gateway_security_group_id = "sg-0gateway"
  image_id                  = "ami-0host"
}

run "a_closed_machine_reaches_the_gateway_alone" {
  command = plan

  assert {
    condition     = aws_vpc_security_group_egress_rule.closed_to_gateway.referenced_security_group_id == "sg-0gateway"
    error_message = "the closed group's one way out is the gateway's group"
  }

  assert {
    condition     = aws_vpc_security_group_egress_rule.closed_to_gateway.from_port == 443 && aws_vpc_security_group_egress_rule.closed_to_gateway.to_port == 443 && aws_vpc_security_group_egress_rule.closed_to_gateway.ip_protocol == "tcp"
    error_message = "on 443 alone"
  }

  assert {
    condition     = aws_vpc_security_group_egress_rule.closed_to_gateway.cidr_ipv4 == null && aws_vpc_security_group_egress_rule.closed_to_gateway.cidr_ipv6 == null
    error_message = "the closed group names no address range"
  }
}

run "an_open_machine_adds_open_egress_and_nothing_reaches_in" {
  # Applied against the mock provider, so the groups' rules as built read.
  command = apply

  assert {
    condition     = aws_vpc_security_group_egress_rule.open_ipv4.cidr_ipv4 == "0.0.0.0/0" && aws_vpc_security_group_egress_rule.open_ipv6.cidr_ipv6 == "::/0"
    error_message = "the open group opens egress, the session's recorded choice"
  }

  assert {
    condition     = length([for rule in [aws_security_group.closed, aws_security_group.open] : rule if length(rule.ingress) > 0]) == 0
    error_message = "neither group admits anything in"
  }
}

run "a_machine_holds_no_role_and_its_disk_is_sealed_under_the_pools_key" {
  command = plan

  assert {
    condition     = length(aws_launch_template.machine.iam_instance_profile) == 0
    error_message = "a machine holds no instance role: its metadata endpoint hands out no credential"
  }

  assert {
    condition     = aws_launch_template.machine.metadata_options[0].http_tokens == "required" && aws_launch_template.machine.metadata_options[0].http_put_response_hop_limit == 1
    error_message = "the metadata endpoint answers a session token alone, and nothing past the guest"
  }

  assert {
    condition     = aws_launch_template.machine.block_device_mappings[0].ebs[0].encrypted == "true" && aws_launch_template.machine.block_device_mappings[0].ebs[0].kms_key_id == "arn:aws:kms:us-west-2:123456789012:key/disks"
    error_message = "the disk, and every snapshot of it, is encrypted under the pool's key"
  }

  assert {
    condition     = aws_launch_template.machine.vpc_security_group_ids == null || length(aws_launch_template.machine.vpc_security_group_ids) == 0
    error_message = "the group is the start's to name, by the session's egress"
  }
}

run "the_platforms_hold_starts_machines_from_the_template_and_passes_no_role" {
  command = plan

  assert {
    condition     = length([for statement in data.aws_iam_policy_document.operate.statement : statement if contains(statement.actions, "iam:PassRole")]) == 0
    error_message = "the runner and the sweep pass no role to a machine"
  }

  assert {
    condition     = contains(one([for statement in data.aws_iam_policy_document.operate.statement : statement.resources if statement.sid == "StartFromTheTemplate"]), aws_launch_template.machine.arn) || aws_launch_template.machine.arn == null
    error_message = "a machine starts from the pool's launch template"
  }

  assert {
    condition     = [for condition in one([for statement in data.aws_iam_policy_document.operate.statement : statement.condition if statement.sid == "OperateItsOwn"]) : condition.variable] == ["aws:ResourceTag/acme:machine"]
    error_message = "only what carries a machine's name is stopped, snapshotted, or ended"
  }
}
