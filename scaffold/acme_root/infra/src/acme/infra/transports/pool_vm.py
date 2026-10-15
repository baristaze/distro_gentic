"""The transport of the VM this process runs in, when the VM is a
session's own (`acme.infra.agent_workspaces.pool_vm`): its commands are processes
of this host, in the workspace's folder, as the local transport runs them."""

from pathlib import Path

from acme.infra.agent_workspaces import AgentWorkspace, IsolationMode
from acme.infra.transports import require_mode
from acme.infra.transports.local import TransportLocalImpl


class TransportPoolVmImpl(TransportLocalImpl):
    """The local transport, held to a VM's workspace at the VM's
    level."""

    def _root(self, workspace: AgentWorkspace) -> Path:
        require_mode(workspace, IsolationMode.VM, "vm")
        return Path(workspace.location).resolve()

    def describe(self) -> str:
        return "transport=vm"
