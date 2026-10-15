"""The cloud pool: one virtual machine per session that runs in the
platform's cloud, through the machines' backend. Each machine runs the same
host program a customer installs: it trades the key it was handed at its
start for a host's credential of its session's pool of one, claims that
session's work alone through the relay, and holds no credential of the
platform's. Its session's next loop starts it again from the session's
latest snapshot, which is the machine's whole disk."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.infra.agent_workspaces import AgentWorkspace, IsolationSpec
from acme.om.agent_workspaces.types.snapshot import KeptSnapshot
from acme.om.cloud_pool.types.machine import MachineSnapshot
from acme.om.context import RequestContext, TenantContext, stageless, transition
from acme.om.hosts.types.credential import IssuedCredential
from acme.om.hosts.types.host import Enrollment


class CloudPoolManagerInterface(ABC):
    @abstractmethod
    @stageless
    async def runs(self, spec: IsolationSpec) -> bool:
        """System-internal: whether a session of the cloud at this spec
        runs on a machine of the pool, which the transport asks of the spec
        alone, before any stage: the pool runs machines here, and the spec
        asks for a VM."""
        ...

    @abstractmethod
    async def prepare(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: KeptSnapshot | None = None,
    ) -> AgentWorkspace:
        """The session's workspace on its machine, once the machine's host
        holds it. The machine is the one that serves the session, else a
        warm one it claims, else one started from the pool's image; with
        `restore`, one started from that snapshot of the session's machine,
        held to its digest first. `IsolationRefused` that clears while the
        machine starts or its host has not prepared it in time, and the loop
        waits on the resource; one that never clears for a spec the pool's
        machines cannot hold. `AgentWorkspaceLost` when the snapshot is gone, was
        not taken by the pool, or does not match its digest."""
        ...

    @abstractmethod
    async def snapshot(self, ctx: TenantContext, agent_session_id: UUID) -> MachineSnapshot:
        """Keeps the session's machine whole: its host's credential is ended
        first, so the disk holds no credential that answers, then the
        machine is stopped and its disk kept as a snapshot under the
        session's names. The stopped machine stays until it is released, so
        a snapshot whose record does not land loses nothing: the next
        prepare starts the machine again. `SnapshotRefused` when no machine
        serves the session."""
        ...

    @abstractmethod
    async def holds(self, ctx: TenantContext, agent_session_id: UUID) -> bool:
        """Whether a machine of the pool serves the session."""
        ...

    @abstractmethod
    async def release(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        """Lets go of the machine that serves the session: its host's
        credential ends and the machine goes, its disk with it."""
        ...

    @abstractmethod
    @stageless
    async def purge(self, org_id: UUID, agent_session_id: UUID) -> None:
        """System-internal: the session's purge, which runs for no
        principal: its machine and every snapshot kept under its names
        go."""
        ...

    @abstractmethod
    @stageless
    async def erase(self, org_id: UUID, agent_session_id: UUID) -> None:
        """System-internal: the revocation of the session's key, named with
        its tenant: every snapshot kept under its names goes. Its machine, a
        cache, stays. The erasure is asked first, and done at once where this
        process reaches the machines; elsewhere, as in the API's process, the
        sweep does it."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """A tenant's purge, once it was deleted past its retention: every
        machine that serves one of its sessions goes, and every snapshot
        kept under its names. Answers how many went; a tenant not past its
        retention loses nothing."""
        ...

    @abstractmethod
    @transition
    async def enroll(
        self, rctx: RequestContext, key: str, enrollment: Enrollment
    ) -> IssuedCredential:
        """System-internal: a machine's host trades its key, once, for a
        credential of its session's pool of one; the host is no person, so
        it calls from the request stage. `MachineUnbound` while the machine
        is warm, and serves no session yet; `InvalidCredential` for a key
        never handed, or spent."""
        ...

    @abstractmethod
    @transition
    async def sweep(self, rctx: RequestContext) -> int:
        """System-internal: one pass of the sweep, across tenants and for
        none, over every machine the pool holds, a page at a time: lets go of
        a machine whose first start died with the process that started it,
        of one whose session, or tenant, is gone, and of one under the pool's
        names that no row holds; stops a session's machine that runs with no
        host to work for, its host never enrolled, ended, or silent, and
        keeps its disk; does the erasures asked; then starts warm machines
        until the pool's warm count stands. Answers how many machines it let
        go or stopped."""
        ...

    @abstractmethod
    @stageless
    async def close(self) -> None:
        """System-internal: at shutdown, waits out the warm starts this
        process began."""
        ...
