# The cloud pool's machines (ADR 2052): each one a VM a session of the
# platform's cloud runs on, with Docker inside and the host program, which
# pulls its session's work from the gateway. The platform never calls in.
#
# A machine holds nothing to steal. It starts with no instance role, so its
# metadata endpoint hands out no credential, and the endpoint is closed once
# its host has read the seed the pool handed it. Its egress is closed at the
# network: the closed group reaches the gateway alone, and the open group
# adds the open egress a session's policy chose. Neither admits anything in.
# Its disk, and every snapshot the pool keeps of it, are encrypted under the
# pool's own key.

locals {
  name = "acme-${var.environment}-cloud-pool"
  tags = { "acme:component" = "cloud-pool", "acme:environment" = var.environment }
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

resource "aws_kms_key" "disks" {
  description         = "The cloud pool's machine disks and the snapshots kept of them"
  enable_key_rotation = true
  tags                = local.tags
}

resource "aws_kms_alias" "disks" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.disks.key_id
}

resource "aws_security_group" "closed" {
  name        = "${local.name}-closed"
  description = "A machine that reaches nothing but the gateway."
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
  description = "A machine whose session's policy chose open egress."
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

resource "aws_launch_template" "machine" {
  name          = local.name
  description   = "A machine of the cloud pool: no role, metadata by token alone, an encrypted disk"
  image_id      = var.image_id
  instance_type = var.instance_type

  # No iam_instance_profile: a machine holds no credential of the cloud's.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  block_device_mappings {
    device_name = data.aws_ami.image.root_device_name
    ebs {
      volume_size           = var.disk_gb
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
}

# What the platform's runner and its sweep may do to the pool's machines,
# and nothing more: start one from the pool's template and only with its
# name's tag, then stop, start, seal, snapshot, and end only what carries
# one. It passes no role, so no machine ever holds one.
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
      aws_launch_template.machine.arn,
      "arn:${data.aws_partition.current.partition}:ec2:${data.aws_region.current.region}::image/*",
      "arn:${data.aws_partition.current.partition}:ec2:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:*",
    ]
  }

  statement {
    sid       = "NameWhatItMakes"
    actions   = ["ec2:CreateTags"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:CreateAction"
      values   = ["RunInstances", "CreateImage", "CopyImage"]
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
      "ec2:CreateImage",
      "ec2:CopyImage",
      "ec2:DeregisterImage",
      "ec2:DeleteSnapshot",
      "ebs:ListSnapshotBlocks",
      "ebs:GetSnapshotBlock",
    ]
    resources = ["*"]
    condition {
      test     = "Null"
      variable = "aws:ResourceTag/acme:machine"
      values   = ["false"]
    }
  }

  statement {
    sid       = "UseTheDiskKey"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey", "kms:CreateGrant"]
    resources = [aws_kms_key.disks.arn]
  }
}

resource "aws_iam_policy" "operate" {
  name        = "${local.name}-operate"
  description = "The runner's and the sweep's hold on the cloud pool's machines"
  policy      = data.aws_iam_policy_document.operate.json
  tags        = local.tags
}
