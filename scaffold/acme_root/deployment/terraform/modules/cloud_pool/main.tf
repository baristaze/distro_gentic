# The cloud pool's VMs (ADR 2052): each one a VM a session of the
# platform's cloud runs on, with Docker inside and the host program, which
# pulls its session's work from the gateway. The platform never calls in.
#
# A VM holds nothing to steal. It starts with no instance role, so its
# metadata endpoint hands out no credential, and the endpoint is closed once
# its host has read the seed the pool handed it. Its egress is closed at the
# network: the closed group reaches the gateway alone, and the open group
# adds the open egress a session's policy chose. Neither admits anything in.
# Its disk is encrypted under the pool's own key, and the pool keeps no image
# or snapshot of it: a session's files are kept sealed in the snapshots
# bucket, under the session's key (ADR 2070). Its size is one of the size map's machine types, the only
# ones the platform's role may launch (ADR 2069). With `hibernation`, a warm VM
# may sleep, its memory written to its encrypted disk holding no key
# (ADR 2075): the template sets it at launch, every type of the map must
# hibernate, and the disk holds the largest size's memory too.

locals {
  name = "acme-${var.environment}-cloud-pool"
  tags = { "acme:component" = "cloud-pool", "acme:environment" = var.environment }
  # The machine types the size map names, each once: what a VM may run on.
  types = sort(distinct([for size in values(var.sizes) : size.type]))
  # A VM that hibernates writes its memory to its root disk, so the disk
  # holds the largest size's memory beside the room a session's work takes.
  memory_gb = ceil(max([for size in values(var.sizes) : size.memory_mb]...) / 1024)
  disk_gb   = var.disk_gb + (var.hibernation ? local.memory_gb : 0)
  # Every call that makes a disk image or a volume snapshot, or copies one in.
  disk_copies = [
    "ebs:StartSnapshot",
    "ec2:CopyImage",
    "ec2:CopySnapshot",
    "ec2:CreateImage",
    "ec2:CreateRestoreImageTask",
    "ec2:CreateSnapshot",
    "ec2:CreateSnapshots",
    "ec2:CreateStoreImageTask",
    "ec2:ImportImage",
    "ec2:ImportSnapshot",
    "ec2:RegisterImage",
  ]
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

# The pool's image, read for the device its root disk boots from: the
# template maps that device, so the root disk itself is the one encrypted
# under the pool's key, whatever device the image names.
data "aws_ami" "image" {
  filter {
    name   = "image-id"
    values = [var.image_id]
  }
}

# Each machine type of the map, read for whether it hibernates, where a VM
# may: a type that cannot is refused at plan, since a VM launched on one
# would fail only as it went to sleep.
data "aws_ec2_instance_type" "sized" {
  for_each      = var.hibernation ? toset(local.types) : toset([])
  instance_type = each.value
}

resource "aws_kms_key" "disks" {
  description         = "The cloud pool's VM disks"
  enable_key_rotation = true
  tags                = local.tags
}

resource "aws_kms_alias" "disks" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.disks.key_id
}

resource "aws_security_group" "closed" {
  name        = "${local.name}-closed"
  description = "A VM that reaches nothing but the gateway."
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_vpc_security_group_egress_rule" "closed_to_gateway" {
  security_group_id            = aws_security_group.closed.id
  referenced_security_group_id = var.gateway_security_group_id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
  description                  = "The gateway, where the host pulls its session's work."
}

resource "aws_security_group" "open" {
  name        = "${local.name}-open"
  description = "A VM whose session's policy chose open egress."
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_vpc_security_group_egress_rule" "open_ipv4" {
  security_group_id = aws_security_group.open.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Open egress, the session's recorded choice."
}

resource "aws_vpc_security_group_egress_rule" "open_ipv6" {
  security_group_id = aws_security_group.open.id
  cidr_ipv6         = "::/0"
  ip_protocol       = "-1"
  description       = "Open egress, the session's recorded choice."
}

resource "aws_launch_template" "vm" {
  name          = local.name
  description   = "A VM of the cloud pool: no role, metadata by token alone, an encrypted disk"
  image_id      = var.image_id
  instance_type = var.sizes["s"].type

  # No iam_instance_profile: a VM holds no credential of the cloud's.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  # Set at launch, as no VM takes it later; the disk it writes the memory
  # to is the encrypted root disk below.
  hibernation_options {
    configured = var.hibernation
  }

  block_device_mappings {
    device_name = data.aws_ami.image.root_device_name
    ebs {
      volume_size           = local.disk_gb
      volume_type           = "gp3"
      encrypted             = true
      kms_key_id            = aws_kms_key.disks.arn
      delete_on_termination = true
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags          = local.tags
  }

  tag_specifications {
    resource_type = "volume"
    tags          = local.tags
  }

  tags = local.tags

  lifecycle {
    precondition {
      condition     = alltrue([for type in values(data.aws_ec2_instance_type.sized) : type.hibernation_supported])
      error_message = "Every machine type the size map names hibernates, where a VM may: ${join(", ", sort([for name, type in data.aws_ec2_instance_type.sized : name if !type.hibernation_supported]))} cannot."
    }
  }
}

# What the platform's runner and its sweep may do to the pool's VMs,
# and nothing more: start one from the pool's template, of a type the size
# map names, and only with its name's tag, then stop, start, seal, and end
# only what carries one, never moving one to another type. It makes no disk
# image and no volume snapshot, of a VM or of anything else. It passes no
# role, so no VM ever holds one.
data "aws_iam_policy_document" "operate" {
  statement {
    sid       = "Read"
    actions   = ["ec2:DescribeInstances", "ec2:DescribeImages", "ec2:DescribeLaunchTemplates"]
    resources = ["*"]
  }

  statement {
    sid     = "StartFromTheTemplate"
    actions = ["ec2:RunInstances"]
    resources = [
      aws_launch_template.vm.arn,
      "arn:${data.aws_partition.current.partition}:ec2:${data.aws_region.current.region}::image/*",
      "arn:${data.aws_partition.current.partition}:ec2:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:*",
    ]
  }

  # A start names its type, or takes the template's; either way the
  # instance is one of the map's, or nothing starts.
  statement {
    sid       = "OnlyTheSizesTypes"
    effect    = "Deny"
    actions   = ["ec2:RunInstances"]
    resources = ["arn:${data.aws_partition.current.partition}:ec2:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:instance/*"]
    condition {
      test     = "StringNotEquals"
      variable = "ec2:InstanceType"
      values   = local.types
    }
  }

  # A stopped VM moved to a type the map does not name would start as one.
  statement {
    sid       = "NoOtherTypeLater"
    effect    = "Deny"
    actions   = ["ec2:ModifyInstanceAttribute"]
    resources = ["*"]
    condition {
      test     = "Null"
      variable = "ec2:Attribute/InstanceType"
      values   = ["false"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "ec2:Attribute/InstanceType"
      values   = local.types
    }
  }

  statement {
    sid       = "NameWhatItMakes"
    actions   = ["ec2:CreateTags"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:CreateAction"
      values   = ["RunInstances"]
    }
  }

  statement {
    sid = "OperateItsOwn"
    actions = [
      "ec2:StopInstances",
      "ec2:StartInstances",
      "ec2:TerminateInstances",
      "ec2:ModifyInstanceAttribute",
      "ec2:ModifyInstanceMetadataOptions",
    ]
    resources = ["*"]
    condition {
      test     = "Null"
      variable = "aws:ResourceTag/acme:vm"
      values   = ["false"]
    }
  }

  # A copy of a VM's disk would be kept outside the session's seal, so
  # nothing this role does makes one, whatever another statement allows.
  statement {
    sid       = "NoDiskImage"
    effect    = "Deny"
    actions   = local.disk_copies
    resources = ["*"]
  }

  statement {
    sid       = "UseTheDiskKey"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey", "kms:CreateGrant"]
    resources = [aws_kms_key.disks.arn]
  }
}

resource "aws_iam_policy" "operate" {
  name        = "${local.name}-operate"
  description = "The runner's and the sweep's hold on the cloud pool's VMs"
  policy      = data.aws_iam_policy_document.operate.json
  tags        = local.tags
}
