"""The cloud pool: one VM per session that runs in the
platform's cloud, through the VMs' backend. Each VM runs the same
host program a customer installs: it trades the key it was handed at its
start for a host's credential of its session's pool of one, claims that
session's work alone through the relay, and holds no credential of the
platform's. Its session's next loop starts it again from the session's
latest snapshot, which is the VM's whole disk."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.infra.agent_workspaces import AgentWorkspace, IsolationSpec
from acme.om.agent_workspaces.types.snapshot import KeptSnapshot
from acme.om.cloud_pool.types.vm import VmSnapshot
from acme.om.context import RequestContext, TenantContext, stageless, transition
from acme.om.hosts.types.credential import IssuedCredential
from acme.om.hosts.types.host import Enrollment


class CloudPoolManagerInterface(ABC):
    @abstractmethod
    @stageless
    async def runs(self, spec: IsolationSpec) -> bool:
        """System-internal: whether a session of the cloud at this spec
        runs on a VM of the pool, which the transport asks of the spec
        alone, before any stage: the pool runs VMs here, and the spec
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
        """The session's workspace on its VM, once the VM's host
        holds it. The VM is the one that serves the session, else a
        warm one it claims, else one started from the pool's image; with
        `restore`, one started from that snapshot of the session's VM,
        held to its digest first. `IsolationRefused` that clears while the
        VM starts or its host has not prepared it in time, and the loop
        waits on the resource; one that never clears for a spec the pool's
        VMs cannot hold. `AgentWorkspaceLost` when the snapshot is gone, was
        not taken by the pool, or does not match its digest."""
        ...

    @abstractmethod
    async def snapshot(self, ctx: TenantContext, agent_session_id: UUID) -> VmSnapshot:
        """Keeps the session's VM whole: its host's credential is ended
        first, so the disk holds no credential that answers, then the
        VM is stopped and its disk kept as a snapshot under the
        session's names. The stopped VM stays until it is released, so
        a snapshot whose record does not land loses nothing: the next
        prepare starts the VM again. `SnapshotRefused` when no VM
        serves the session."""
        ...

    @abstractmethod
    async def holds(self, ctx: TenantContext, agent_session_id: UUID) -> bool:
        """Whether a VM of the pool serves the session."""
        ...

    @abstractmethod
    async def release(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        """Lets go of the VM that serves the session: its host's
        credential ends and the VM goes, its disk with it."""
        ...

    @abstractmethod
    @stageless
    async def purge(self, org_id: UUID, agent_session_id: UUID) -> None:
        """System-internal: the session's purge, which runs for no
        principal: its VM and every snapshot kept under its names
        go."""
        ...

    @abstractmethod
    @stageless
    async def erase(self, org_id: UUID, agent_session_id: UUID) -> None:
        """System-internal: the revocation of the session's key, named with
        its tenant: every snapshot kept under its names goes. Its VM, a
        cache, stays. The erasure is asked first, and done at once where this
        process reaches the VMs; elsewhere, as in the API's process, the
        sweep does it."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """A tenant's purge, once it was deleted past its retention: every
        VM that serves one of its sessions goes, and every snapshot
        kept under its names. Answers how many went; a tenant not past its
        retention loses nothing."""
        ...

    @abstractmethod
    @transition
    async def enroll(
        self, rctx: RequestContext, key: str, enrollment: Enrollment
    ) -> IssuedCredential:
        """System-internal: a VM's host trades its key, once, for a
        credential of its session's pool of one; the host is no person, so
        it calls from the request stage. `VmUnbound` while the VM
        is warm, and serves no session yet; `InvalidCredential` for a key
        never handed, or spent."""
        ...

    @abstractmethod
    @transition
    async def sweep(self, rctx: RequestContext) -> int:
        """System-internal: one pass of the sweep, across tenants and for
        none, over every VM the pool holds, a page at a time: lets go of
        a VM whose first start died with the process that started it,
        of one whose session, or tenant, is gone, and of one under the pool's
        names that no row holds; stops a session's VM that runs with no
        host to work for, its host never enrolled, ended, or silent, and
        keeps its disk; does the erasures asked; then starts warm VMs
        until the pool's warm count stands. Answers how many VMs it let
        go or stopped."""
        ...

    @abstractmethod
    @stageless
    async def close(self) -> None:
        """System-internal: at shutdown, waits out the warm starts this
        process began."""
        ...
