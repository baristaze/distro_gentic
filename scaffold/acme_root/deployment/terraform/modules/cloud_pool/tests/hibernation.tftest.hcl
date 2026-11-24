# With `hibernation`, a VM of the template may sleep: the template sets it at
# launch, since no VM takes it later; the root disk adds the largest size's
# memory, which a VM writes there as it sleeps; and a size map that names a
# type that cannot hibernate is refused at plan, since a VM of it would fail
# only in the cloud. The disk's encryption under the pool's key is
# walls.tftest.hcl's. Without it, the template sets none, the disk is the
# map's own, and no type is read.
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
  mock_data "aws_ec2_instance_type" {
    defaults = { hibernation_supported = true }
  }
}

variables {
  environment               = "staging"
  vpc_id                    = "vpc-0pool"
  subnet_ids                = ["subnet-0a", "subnet-0b"]
  gateway_security_group_id = "sg-0gateway"
  image_id                  = "ami-0host"
  allowed_names             = ["gateway.pool.acme.internal"]
  disk_gb                   = 64
  sizes = {
    xs = { type = "m7g.medium", cpus = 1, memory_mb = 4096 }
    s  = { type = "m7g.large", cpus = 2, memory_mb = 8192 }
    m  = { type = "m7g.xlarge", cpus = 4, memory_mb = 16384 }
  }
}

run "a_template_that_hibernates_sets_it_at_launch_and_its_disk_holds_the_memory" {
  command = plan

  variables {
    hibernation = true
  }

  assert {
    condition     = aws_launch_template.vm.hibernation_options[0].configured == true
    error_message = "hibernation is set at launch, or no VM of the template ever sleeps"
  }

  assert {
    condition     = aws_launch_template.vm.block_device_mappings[0].ebs[0].volume_size == 64 + 16
    error_message = "the root disk adds the largest size's memory, 16 GiB, to the session's room"
  }

  assert {
    condition     = toset(keys(data.aws_ec2_instance_type.sized)) == toset(["m7g.medium", "m7g.large", "m7g.xlarge"])
    error_message = "every type the map names is read for whether it hibernates"
  }

  assert {
    condition     = output.hibernation == true
    error_message = "ACME_VM_HIBERNATION tells the platform its VMs may sleep"
  }
}

run "a_map_naming_a_type_that_cannot_hibernate_is_refused_while_the_tier_is_on" {
  command = plan

  variables {
    hibernation = true
  }

  override_data {
    target = data.aws_ec2_instance_type.sized
    values = { hibernation_supported = false }
  }

  expect_failures = [aws_launch_template.vm]
}

run "without_hibernation_the_template_sets_none_and_reads_no_type" {
  command = plan

  override_data {
    target = data.aws_ec2_instance_type.sized
    values = { hibernation_supported = false }
  }

  assert {
    condition     = aws_launch_template.vm.hibernation_options[0].configured == false
    error_message = "no VM sleeps where the tier is off"
  }

  assert {
    condition     = aws_launch_template.vm.block_device_mappings[0].ebs[0].volume_size == 64
    error_message = "the disk is the session's room alone"
  }

  assert {
    condition     = length(data.aws_ec2_instance_type.sized) == 0
    error_message = "no type is read, so none is refused"
  }

  assert {
    condition     = output.hibernation == false
    error_message = "ACME_VM_HIBERNATION stays false"
  }
}
