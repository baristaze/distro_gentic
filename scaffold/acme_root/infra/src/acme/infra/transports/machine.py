"""The transport of the machine this process runs in, when the machine is a
session's own (`acme.infra.agent_workspaces.machine`): its commands are processes
of this host, in the workspace's folder, as the local transport runs them."""

from pathlib import Path

from acme.infra.agent_workspaces import AgentWorkspace, IsolationMode
from acme.infra.transports import require_mode
from acme.infra.transports.local import TransportLocalImpl


class TransportMachineImpl(TransportLocalImpl):
    """The local transport, held to a machine's workspace at the VM's
    level."""

    def _root(self, workspace: AgentWorkspace) -> Path:
        require_mode(workspace, IsolationMode.VM, "machine")
        return Path(workspace.location).resolve()

    def describe(self) -> str:
        return "transport=machine"
