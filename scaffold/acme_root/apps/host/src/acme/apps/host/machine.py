"""The host as a machine of the platform's cloud pool runs it: inside a
virtual machine the pool started for one session, so the machine is that
session's wall. It enrolls with the key the pool handed the machine, in its
seed, rather than a tenant's enrollment token, and it claims its session's
work alone, which the platform holds it to.

Its workspace is a folder in the machine, at the VM's level. Its commands
run as the host's own user, in Docker's group, so they build and run
containers of their own: the machine's root is theirs through Docker, as a
VM workspace's commands hold their guest whole. Its egress is the machine's,
closed at the machine's network by the pool to what the session's spec
asks. It keeps no snapshot and starts from none: the pool keeps the
machine's whole disk, and starts the machine again from it."""

import asyncio
from pathlib import Path
from uuid import UUID

from acme.apps.host.probe import Probe, Probes, container
from acme.client.types import IsolationMode as HostIsolation
from acme.infra.transports import require_mode
from acme.infra.transports.local import TransportLocalImpl
from acme.infra.workspaces import (
    EgressMode,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    SnapshotRefused,
    Workspace,
    refusal,
)
from acme.infra.workspaces.host import WorkspaceHostImpl

KEPT_BY_THE_POOL = "the cloud pool keeps this machine's whole disk, and the host takes none"


def machine_probes() -> Probes:
    """A machine's probes: its level is the VM's while Docker answers its
    commands, and its metadata endpoint is the pool's to close, which the
    pool does before its session's work comes."""
    return Probes(
        isolation={HostIsolation.vm: machine},
        metadata=lambda: Probe(
            "metadata", True, "the cloud pool closes this machine's metadata endpoint"
        ),
    )


def machine() -> Probe:
    """A VM per session: this host runs in a machine its pool started for one
    session, and Docker answers its commands there."""
    engine = container()
    if not engine.passed:
        return Probe("vm", False, f"a machine of the cloud pool, and {engine.detail}")
    return Probe("vm", True, f"a machine of the cloud pool, and {engine.detail}")


class WorkspaceMachineImpl(WorkspaceHostImpl):
    """The workspace of a machine the cloud pool started for one session: a
    folder under `root`, at the VM's level. It holds open egress and none
    alike, which the machine's network enforces, and no allowlist and no
    limit of its own. Its release ends what its commands left running and
    keeps its files, as a host directory's does."""

    async def prepare(
        self,
        org_id: UUID,
        workspace_id: UUID,
        spec: IsolationSpec,
        snapshot: bytes | None = None,
        base: bytes | None = None,
        *,
        building: bool = False,
    ) -> Workspace:
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
        directory = self._directory(org_id, workspace_id)
        await asyncio.to_thread(directory.mkdir, mode=0o700, parents=True, exist_ok=True)
        await asyncio.to_thread(self._mark(org_id, workspace_id).touch, mode=0o600)
        return Workspace(id=workspace_id, org_id=org_id, spec=spec, location=str(directory))

    async def snapshot(self, workspace: Workspace) -> bytes:
        raise SnapshotRefused(KEPT_BY_THE_POOL)

    def describe(self) -> str:
        return f"workspaces=machine({self._root})"


class TransportMachineImpl(TransportLocalImpl):
    """The local transport, in a machine's workspace: its commands are
    processes of this host, in the workspace's folder."""

    def _root(self, workspace: Workspace) -> Path:
        require_mode(workspace, IsolationMode.VM, "machine")
        return Path(workspace.location).resolve()

    def describe(self) -> str:
        return "transport=machine"
