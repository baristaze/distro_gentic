# A VM's disk loads the image's blocks at their first read unless an
# operator sets a rate: no rate is charged on any VM by default. A rate
# set reaches the root disk as it is, and a rate EBS would refuse at a
# launch is refused at the plan.
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
  allowed_names             = ["gateway.pool.acme.internal"]
}

# A rate the template leaves null is known only once it is applied: the
# mock, like the provider, then reads it as 0, which EBS takes as none.
run "no_rate_is_set_unless_an_operator_sets_one" {
  command = apply

  assert {
    condition     = aws_launch_template.vm.block_device_mappings[0].ebs[0].volume_initialization_rate == 0
    error_message = "the root disk names no rate, so no VM is charged for one no operator chose"
  }
}

run "a_rate_set_reaches_the_root_disk" {
  command = plan

  variables {
    volume_initialization_rate = 300
  }

  assert {
    condition     = aws_launch_template.vm.block_device_mappings[0].ebs[0].volume_initialization_rate == 300
    error_message = "the root disk loads at the rate the operator set"
  }
}

run "the_lowest_rate_is_allowed" {
  command = plan

  variables {
    volume_initialization_rate = 100
  }

  assert {
    condition     = aws_launch_template.vm.block_device_mappings[0].ebs[0].volume_initialization_rate == 100
    error_message = "100 MiB/s, the lowest rate EBS takes, is allowed"
  }
}

run "a_rate_below_100_is_refused" {
  command = plan

  variables {
    volume_initialization_rate = 99
  }

  expect_failures = [var.volume_initialization_rate]
}

run "a_rate_above_300_is_refused" {
  command = plan

  variables {
    volume_initialization_rate = 301
  }

  expect_failures = [var.volume_initialization_rate]
}

run "a_rate_in_part_of_a_mib_is_refused" {
  command = plan

  variables {
    volume_initialization_rate = 150.5
  }

  expect_failures = [var.volume_initialization_rate]
}
