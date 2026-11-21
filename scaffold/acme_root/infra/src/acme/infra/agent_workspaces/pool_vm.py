"""The workspace of the VM this process runs in, when the VM is a
session's own: a VM of the platform's cloud pool, where the host
program runs and the pool started the VM for one session. The VM
is the session's wall, so its workspace is a folder in it, at the VM's
level, and its commands hold the guest whole, as a VM workspace's do
(ADR 2052). The platform keeps its directory, reaching it through the
relay as it reaches any of the host's workspaces (ADR 2070)."""

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

KEPT_BY_THE_POOL = (
    "the platform keeps this VM's directory through the relay, and the host takes no snapshot"
)


class AgentWorkspacePoolVmImpl(AgentWorkspaceHostImpl):
    """A folder under `root`, at the VM's level. It holds open egress and
    none alike, which the VM's network enforces, and the size the pool
    started the VM to, and no allowlist and no other limit. It keeps no
    snapshot and starts from none, nor from a base: the platform packs the
    directory, reads it out, and brings it back into a new VM through the
    relay, and every VM starts from the pool's image. Its release ends
    what its commands left running and keeps its files, as a host
    directory's does. Its `check` refuses what its `prepare` refuses of the
    spec alone."""

    async def check(self, spec: IsolationSpec) -> None:
        why = _refusal(spec)
        if why is not None:
            raise IsolationRefused(why, cause=why)

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
        why = _refusal(spec)
        if why is None and (snapshot is not None or base is not None):
            why = _FROM_THE_POOL
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
        return f"workspaces=vm({self._root})"


_FROM_THE_POOL = "a VM's workspace starts from the pool's image: " + KEPT_BY_THE_POOL


def _refusal(spec: IsolationSpec) -> str | None:
    """Why a VM of the pool never holds `spec`: another level, an egress
    its network cannot hold, a limit other than its size, or a base."""
    why = refusal(
        spec,
        mode=IsolationMode.VM,
        egress={EgressMode.OPEN, EgressMode.NONE},
        limits=("size",),
    )
    if why is None and spec.base is not None:
        why = _FROM_THE_POOL
    return why
