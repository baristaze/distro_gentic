"""The platform's infra settings, a section of their own that the
guideline's `InfraSettings` takes in under its prefix and its file: the
image and the deployment a container workspace carries, the image pull's
limit, a VM of the platform's cloud account, and the cloud pool."""

from pydantic import Field
from pydantic_settings import BaseSettings

from acme.infra.agent_workspaces.container import DEFAULT_IMAGE


class PlatformInfraSettings(BaseSettings):
    # The image a container workspace runs: a session checks out and pushes
    # its repository inside it, so the platform's default holds `git`.
    agent_workspace_image: str = DEFAULT_IMAGE
    # Each container workspace carries the deployment's name, and a runner
    # holds only those that carry its own.
    agent_workspace_deployment: str = Field(default="acme-local", min_length=1)
    # `docker pull` of the workspace image, which a prepare runs when the
    # image is absent: the image is large, and a pull cut short leaves
    # nothing, so it has a limit of its own.
    docker_pull_timeout_seconds: float = 900.0
    # `ec2` machines run as instances in the platform's cloud account, from
    # the cloud pool's launch template (`vm_launch_template`), in one of
    # `vm_subnets` (comma separated), and in the security group of
    # their egress: `vm_closed_group` reaches the gateway alone, and
    # `vm_open_group` adds open egress. Their image is an AMI, and their
    # snapshots are the cloud's own, under the template's key. A process on
    # `ec2` never calls into a machine, so no VM workspace runs on it.
    vm_launch_template: str = ""
    vm_subnets: str = ""
    vm_closed_group: str = ""
    vm_open_group: str = ""
    # The cloud pool: a machine per session of the cloud whose workspace is a
    # VM, each running the host program, which reaches the platform at
    # `cloud_pool_api_url`. Every machine starts from `cloud_pool_image`, a
    # snapshot of the machines that holds the host program: a stopped
    # machine's name on Lima, the AMI id on ec2; empty runs no pool.
    # `cloud_pool_warm` machines stand started ahead of demand.
    cloud_pool_image: str = ""
    cloud_pool_api_url: str = ""
    cloud_pool_warm: int = Field(default=0, ge=0)
