# A VM of the cloud pool reaches nothing but the gateway, and what its
# session's policy opened; nothing reaches in; its network resolves the
# names it allows alone, and fails closed; it holds no role; its disk is
# encrypted under the pool's key; and the platform's hold on the VMs
# starts them from the template alone and passes no role. The mock image
# boots from /dev/sda1, as many Linux images do.
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
  mock_data "aws_ami" {
    defaults = { root_device_name = "/dev/sda1" }
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
  allowed_names             = ["gateway.pool.acme.internal", "store.pool.acme.internal"]
}

run "a_closed_vm_reaches_the_gateway_alone" {
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

run "an_open_vm_adds_open_egress_and_nothing_reaches_in" {
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

run "the_pools_network_resolves_the_allowed_names_alone_and_fails_closed" {
  # Applied against the mock provider, so the rules name their lists by id.
  command = apply

  assert {
    condition     = aws_route53_resolver_firewall_domain_list.allowed.domains == toset(["gateway.pool.acme.internal", "store.pool.acme.internal"])
    error_message = "the allowed list is the input's names, exactly"
  }

  assert {
    condition     = aws_route53_resolver_firewall_rule.allow.action == "ALLOW" && aws_route53_resolver_firewall_rule.allow.firewall_domain_list_id == aws_route53_resolver_firewall_domain_list.allowed.id
    error_message = "the allow rule names the allowed list"
  }

  assert {
    condition     = aws_route53_resolver_firewall_rule.allow.firewall_domain_redirection_action == "TRUST_REDIRECTION_DOMAIN"
    error_message = "an allowed name answers through the alias its zone names"
  }

  assert {
    condition     = aws_route53_resolver_firewall_rule.block.action == "BLOCK" && aws_route53_resolver_firewall_rule.block.firewall_domain_list_id == aws_route53_resolver_firewall_domain_list.every_name.id && aws_route53_resolver_firewall_domain_list.every_name.domains == toset(["*"])
    error_message = "the block rule names every other name"
  }

  assert {
    condition     = aws_route53_resolver_firewall_rule.allow.priority < aws_route53_resolver_firewall_rule.block.priority
    error_message = "the allowed names are judged before the block on every name"
  }

  assert {
    condition = (
      aws_route53_resolver_firewall_rule.allow.firewall_rule_group_id == aws_route53_resolver_firewall_rule_group.names.id
      && aws_route53_resolver_firewall_rule.block.firewall_rule_group_id == aws_route53_resolver_firewall_rule_group.names.id
    )
    error_message = "both rules are the one group's"
  }

  assert {
    condition     = aws_route53_resolver_firewall_rule_group_association.names.vpc_id == "vpc-0pool" && aws_route53_resolver_firewall_rule_group_association.names.firewall_rule_group_id == aws_route53_resolver_firewall_rule_group.names.id
    error_message = "the group holds the pool's network"
  }

  assert {
    condition     = aws_route53_resolver_firewall_config.closed.resource_id == "vpc-0pool" && aws_route53_resolver_firewall_config.closed.firewall_fail_open == "DISABLED"
    error_message = "a lookup the firewall cannot judge is refused, never let through"
  }
}

run "a_network_that_resolves_no_name_is_refused" {
  command = plan

  variables {
    allowed_names = []
  }

  expect_failures = [var.allowed_names]
}

run "a_wildcard_name_is_refused" {
  command = plan

  variables {
    allowed_names = ["gateway.pool.acme.internal", "*.acme.example"]
  }

  expect_failures = [var.allowed_names]
}

run "a_vm_holds_no_role_and_its_disk_is_sealed_under_the_pools_key" {
  command = plan

  assert {
    condition     = length(aws_launch_template.vm.iam_instance_profile) == 0
    error_message = "a VM holds no instance role: its metadata endpoint hands out no credential"
  }

  assert {
    condition     = aws_launch_template.vm.metadata_options[0].http_tokens == "required" && aws_launch_template.vm.metadata_options[0].http_put_response_hop_limit == 1
    error_message = "the metadata endpoint answers a session token alone, and nothing past the guest"
  }

  assert {
    condition     = aws_launch_template.vm.block_device_mappings[0].ebs[0].encrypted == "true" && aws_launch_template.vm.block_device_mappings[0].ebs[0].kms_key_id == "arn:aws:kms:us-west-2:123456789012:key/disks"
    error_message = "the disk, and every snapshot of it, is encrypted under the pool's key"
  }

  assert {
    condition     = length(aws_launch_template.vm.block_device_mappings) == 1 && aws_launch_template.vm.block_device_mappings[0].device_name == "/dev/sda1"
    error_message = "the one disk mapped is the image's own root, so no second disk is added and the root is the one encrypted"
  }

  assert {
    condition     = aws_launch_template.vm.vpc_security_group_ids == null || length(aws_launch_template.vm.vpc_security_group_ids) == 0
    error_message = "the group is the start's to name, by the session's egress"
  }
}

run "the_platforms_hold_starts_vms_from_the_template_and_passes_no_role" {
  command = plan

  assert {
    condition     = length([for statement in data.aws_iam_policy_document.operate.statement : statement if contains(statement.actions, "iam:PassRole")]) == 0
    error_message = "the runner and the sweep pass no role to a VM"
  }

  assert {
    condition     = contains(one([for statement in data.aws_iam_policy_document.operate.statement : statement.resources if statement.sid == "StartFromTheTemplate"]), aws_launch_template.vm.arn) || aws_launch_template.vm.arn == null
    error_message = "a VM starts from the pool's launch template"
  }

  assert {
    condition     = [for condition in one([for statement in data.aws_iam_policy_document.operate.statement : statement.condition if statement.sid == "OperateItsOwn"]) : condition.variable] == ["aws:ResourceTag/acme:vm"]
    error_message = "only what carries a VM's name is stopped, snapshotted, or ended"
  }
}

run "the_platforms_hold_makes_no_disk_image_or_volume_snapshot" {
  command = plan

  assert {
    condition = alltrue([
      for action in [
        "ebs:StartSnapshot", "ec2:CopyImage", "ec2:CopySnapshot", "ec2:CreateImage",
        "ec2:CreateRestoreImageTask", "ec2:CreateSnapshot", "ec2:CreateSnapshots",
        "ec2:CreateStoreImageTask", "ec2:ImportImage", "ec2:ImportSnapshot", "ec2:RegisterImage",
      ] : contains(one([for statement in data.aws_iam_policy_document.operate.statement : statement.actions if statement.sid == "NoDiskImage" && statement.effect == "Deny" && statement.resources == toset(["*"])]), action)
    ])
    error_message = "the role is denied every call that makes a disk image or a volume snapshot, on everything"
  }

  assert {
    condition = length([
      for statement in data.aws_iam_policy_document.operate.statement : statement
      if statement.effect != "Deny" && anytrue([for action in statement.actions : can(regex("^\\*$|^(ec2|ebs):.*\\*|^ec2:.*(Image|Snapshots?)$|^ebs:", action)) && action != "ec2:DescribeImages"])
    ]) == 0
    error_message = "no statement allows a disk image, a volume snapshot, or a wildcard over the machines or their disks"
  }
}
