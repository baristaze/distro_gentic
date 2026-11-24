variable "environment" {
  description = "The environment's name, in every resource's."
  type        = string
}

variable "vpc_id" {
  description = "The network the VMs run in, which only the pool uses: its resolver answers `allowed_names` alone, so nothing else in it resolves another name."
  type        = string
}

variable "allowed_names" {
  description = "Every name the pool's network resolves, each whole: the gateway's, as `ACME_CLOUD_POOL_API_URL` names it, and the store's, as `ACME_CLOUD_POOL_S3_ENDPOINT_URL` names it, when a VM reaches the store at a name of its own. The network's resolver refuses every other name."
  type        = list(string)

  validation {
    condition     = length(var.allowed_names) > 0
    error_message = "The pool's network resolves at least the gateway's name, or no VM reaches it."
  }

  validation {
    condition     = alltrue([for name in var.allowed_names : trimspace(name) != "" && !strcontains(name, "*")])
    error_message = "Each name is whole, never a wildcard: a VM could spell what it carries out in the names one allows."
  }
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
  description = "The AMI every VM boots: a Linux with Docker and the host program installed by deployment/vms/install.sh."
  type        = string
}

variable "sizes" {
  description = "Each size a kind may ask its VM by name, and the machine type it starts, with its CPUs and memory: the only types the pool's role may launch. It names `s`, the size of a VM whose kind asks none, and of every warm VM."
  type = map(object({
    type      = string
    cpus      = number
    memory_mb = number
  }))
  default = {
    xs = { type = "m7g.medium", cpus = 1, memory_mb = 4096 }
    s  = { type = "m7g.large", cpus = 2, memory_mb = 8192 }
    m  = { type = "m7g.xlarge", cpus = 4, memory_mb = 16384 }
  }

  validation {
    condition     = contains(keys(var.sizes), "s") && length(setsubtract(keys(var.sizes), ["xs", "s", "m"])) == 0
    error_message = "The sizes are named xs, s, and m, and name s."
  }
}

variable "disk_gb" {
  description = "Every VM's disk, which holds the session's workspace and what its commands install."
  type        = number
  default     = 64
}

variable "volume_initialization_rate" {
  description = "The rate, in MiB/s from 100 to 300, at which EBS loads every block of the image onto each VM's disk from its creation, rather than each block at its first read. Null, the default, sets none. While set, every VM's disk is charged per GiB of the image's snapshot at the rate, apart from the disk's own cost. A region allows 5,000 MiB/s across the disks it creates at once, and a launch past it fails: set a rate whose share fits the most VMs the pool starts at once. An image whose snapshot has fast snapshot restore loads at the rate instead."
  type        = number
  default     = null

  validation {
    condition     = var.volume_initialization_rate == null ? true : var.volume_initialization_rate >= 100 && var.volume_initialization_rate <= 300 && floor(var.volume_initialization_rate) == var.volume_initialization_rate
    error_message = "The rate is a whole number of MiB/s from 100 to 300, or null: EBS refuses a launch at any other."
  }
}
