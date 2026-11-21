"""The sizes a session's spec may ask its VM by name, as a deployment
allows them: each the machine type a VM of that size starts on, with its
cpus and its memory. The cloud pool module writes the same map, and its
role launches those types alone."""

from acme.infra.agent_workspaces import VmSize
from acme.infra.vms import MachineType
from acme.om.base import OmBase


class PoolSizes(OmBase):
    """The machine each size stands for where the deployment allows it,
    and None where it does not. `s` always stands: a spec that asks no
    size gets it, and so does every warm VM."""

    xs: MachineType | None = None
    s: MachineType
    m: MachineType | None = None

    def of(self, size: VmSize) -> MachineType | None:
        """The machine a VM of `size` starts on; None when the deployment
        does not allow it."""
        machine: MachineType | None = getattr(self, size.value)
        return machine

    def allowed(self) -> frozenset[VmSize]:
        """The sizes the deployment allows."""
        return frozenset(size for size in VmSize if self.of(size) is not None)


SIZES = PoolSizes(
    xs=MachineType(name="m7g.medium", cpus=1, memory_mb=4096),
    s=MachineType(name="m7g.large", cpus=2, memory_mb=8192),
    m=MachineType(name="m7g.xlarge", cpus=4, memory_mb=16384),
)
"""The sizes a deployment allows where it names none: the cloud pool
module's own map."""
