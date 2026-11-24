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

variable "hibernation" {
  description = "Whether a VM may hibernate, so the pool keeps warm VMs asleep: the template sets it at launch, since no VM takes it later, and the root disk adds the largest size's memory, which a VM writes there as it sleeps. Every type the size map names must hibernate. ACME_VM_HIBERNATION."
  type        = bool
  default     = false
}
