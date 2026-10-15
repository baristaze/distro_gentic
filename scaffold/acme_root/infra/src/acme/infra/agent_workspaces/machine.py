"""The workspace of the machine this process runs in, when the machine is a
session's own: a machine of the platform's cloud pool, where the host
program runs and the pool started the machine for one session. The machine
is the session's wall, so its workspace is a folder in it, at the VM's
level, and its commands hold the guest whole, as a VM workspace's do
(ADR 2052)."""

import asyncio
from uuid import UUID

from acme.infra.agent_workspaces import (
    AgentWorkspace,
    EgressMode,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    SnapshotRefused,
    refusal,
)
from acme.infra.agent_workspaces.host import AgentWorkspaceHostImpl

KEPT_BY_THE_POOL = "the cloud pool keeps this machine's whole disk, and the host takes none"


class WorkspaceMachineImpl(AgentWorkspaceHostImpl):
    """A folder under `root`, at the VM's level. It holds open egress and
    none alike, which the machine's network enforces, and no allowlist and
    no limit of its own. It keeps no snapshot and starts from none, nor from
    a base: the pool keeps the machine's whole disk, and starts the machine
    again from it. Its release ends what its commands left running and keeps
    its files, as a host directory's does."""

    async def prepare(
        self,
        org_id: UUID,
        agent_workspace_id: UUID,
        spec: IsolationSpec,
        snapshot: bytes | None = None,
        base: bytes | None = None,
        *,
        building: bool = False,
    ) -> AgentWorkspace:
        why = refusal(
            spec, mode=IsolationMode.VM, egress={EgressMode.OPEN, EgressMode.NONE}, limits=()
        )
        if why is None and (snapshot is not None or base is not None or spec.base is not None):
            why = (
                "a machine's workspace starts from the machine as its pool started it: "
                + KEPT_BY_THE_POOL
            )
        if why is not None:
            raise IsolationRefused(why)
        directory = self._directory(org_id, agent_workspace_id)
        await asyncio.to_thread(directory.mkdir, mode=0o700, parents=True, exist_ok=True)
        await asyncio.to_thread(self._mark(org_id, agent_workspace_id).touch, mode=0o600)
        return AgentWorkspace(
            id=agent_workspace_id, org_id=org_id, spec=spec, location=str(directory)
        )

    async def snapshot(self, workspace: AgentWorkspace) -> bytes:
        raise SnapshotRefused(KEPT_BY_THE_POOL)

    def describe(self) -> str:
        return f"workspaces=machine({self._root})"
