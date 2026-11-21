# A VM is one of the size map's machine types, and nothing else: the pool's
# role may launch those types alone, and move no VM to another; a VM whose
# kind asks no size is the map's `s`; and the map reaches the platform as
# its sizes setting. A map without `s`, or with a size the platform does
# not name, is refused.
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
}

variables {
  environment               = "staging"
  vpc_id                    = "vpc-0pool"
  subnet_ids                = ["subnet-0a", "subnet-0b"]
  gateway_security_group_id = "sg-0gateway"
  image_id                  = "ami-0host"
  sizes = {
    xs = { type = "m7g.large", cpus = 2, memory_mb = 8192 }
    s  = { type = "m7g.large", cpus = 2, memory_mb = 8192 }
    m  = { type = "c7g.2xlarge", cpus = 8, memory_mb = 16384 }
  }
}

run "the_pools_role_launches_the_size_maps_types_alone" {
  command = plan

  assert {
    condition     = one([for statement in data.aws_iam_policy_document.operate.statement : statement.effect if statement.sid == "OnlyTheSizesTypes"]) == "Deny"
    error_message = "a start of any other type is denied, whatever else allows it"
  }

  assert {
    condition     = one([for statement in data.aws_iam_policy_document.operate.statement : statement.actions if statement.sid == "OnlyTheSizesTypes"]) == toset(["ec2:RunInstances"])
    error_message = "the denial holds every start"
  }

  assert {
    condition     = one([for statement in data.aws_iam_policy_document.operate.statement : statement.resources if statement.sid == "OnlyTheSizesTypes"]) == toset(["arn:aws:ec2:us-west-2:123456789012:instance/*"])
    error_message = "it reads the type off the instance a start makes"
  }

  assert {
    condition     = [for condition in one([for statement in data.aws_iam_policy_document.operate.statement : statement.condition if statement.sid == "OnlyTheSizesTypes"]) : [condition.test, condition.variable, toset(condition.values)]] == [["StringNotEquals", "ec2:InstanceType", toset(["c7g.2xlarge", "m7g.large"])]]
    error_message = "every type but the map's, each once, is denied"
  }
}

run "no_vm_is_moved_to_a_type_the_map_does_not_name" {
  command = plan

  assert {
    condition     = one([for statement in data.aws_iam_policy_document.operate.statement : statement.effect if statement.sid == "NoOtherTypeLater"]) == "Deny"
    error_message = "a stopped VM moved to another type would start as one"
  }

  assert {
    condition     = one([for statement in data.aws_iam_policy_document.operate.statement : statement.actions if statement.sid == "NoOtherTypeLater"]) == toset(["ec2:ModifyInstanceAttribute"])
    error_message = "the denial holds the change of an attribute"
  }

  assert {
    condition     = toset([for condition in one([for statement in data.aws_iam_policy_document.operate.statement : statement.condition if statement.sid == "NoOtherTypeLater"]) : jsonencode([condition.test, condition.variable, sort(condition.values)])]) == toset([jsonencode(["Null", "ec2:Attribute/InstanceType", ["false"]]), jsonencode(["StringNotEquals", "ec2:Attribute/InstanceType", ["c7g.2xlarge", "m7g.large"]])])
    error_message = "only a change of the type, to one the map does not name, is denied; the group and the seed still change"
  }
}

run "a_vm_that_asks_no_size_is_the_maps_s_and_the_platform_reads_the_map" {
  command = plan

  assert {
    condition     = aws_launch_template.vm.instance_type == "m7g.large"
    error_message = "the template's type is the map's s, a start's when it names none"
  }

  assert {
    condition     = jsondecode(output.sizes) == { xs = { name = "m7g.large", cpus = 2, memory_mb = 8192 }, s = { name = "m7g.large", cpus = 2, memory_mb = 8192 }, m = { name = "c7g.2xlarge", cpus = 8, memory_mb = 16384 } }
    error_message = "ACME_CLOUD_POOL_SIZES carries each size's type, cpus, and memory"
  }
}

run "a_map_without_s_is_refused" {
  command = plan

  variables {
    sizes = { m = { type = "m7g.xlarge", cpus = 4, memory_mb = 16384 } }
  }

  expect_failures = [var.sizes]
}

run "a_size_the_platform_does_not_name_is_refused" {
  command = plan

  variables {
    sizes = {
      s  = { type = "m7g.large", cpus = 2, memory_mb = 8192 }
      xl = { type = "m7g.4xlarge", cpus = 16, memory_mb = 65536 }
    }
  }

  expect_failures = [var.sizes]
}
