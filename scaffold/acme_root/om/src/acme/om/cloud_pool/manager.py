"""The cloud pool: one virtual machine per session that runs in the
platform's cloud, through the machines' backend. Each machine runs the same
host program a customer installs: it trades the key it was handed at its
start for a host's credential of its session's pool of one, claims that
session's work alone through the relay, and holds no credential of the
platform's. Its session's next loop starts it again from the session's
latest snapshot, which is the machine's whole disk."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.infra.workspaces import IsolationSpec, Workspace
from acme.om.cloud_pool.types.machine import MachineSnapshot
from acme.om.context import RequestContext, TenantContext
from acme.om.hosts.types.credential import IssuedCredential
from acme.om.hosts.types.host import Enrollment
from acme.om.workspaces.types.snapshot import KeptSnapshot


class CloudPoolManagerInterface(ABC):
    @abstractmethod
    def runs(self, spec: IsolationSpec) -> bool:
        """Whether a session of the cloud at this spec runs on a machine of
        the pool: the pool runs machines here, and the spec asks for a VM."""
        ...

    @abstractmethod
    async def prepare(
        self,
        ctx: TenantContext,
        session_id: UUID,
        spec: IsolationSpec,
        restore: KeptSnapshot | None = None,
    ) -> Workspace:
        """The session's workspace on its machine, once the machine's host
        holds it. The machine is the one that serves the session, else a
        warm one it claims, else one started from the pool's image; with
        `restore`, one started from that snapshot of the session's machine,
        held to its digest first. `IsolationRefused` that clears while the
        machine starts or its host has not prepared it in time, and the loop
        waits on the resource; one that never clears for a spec the pool's
        machines cannot hold. `WorkspaceLost` when the snapshot is gone, was
        not taken by the pool, or does not match its digest."""
        ...

    @abstractmethod
    async def snapshot(self, ctx: TenantContext, session_id: UUID) -> MachineSnapshot:
        """Keeps the session's machine whole: its host's credential is ended
        first, so the disk holds no credential that answers, then the
        machine is stopped and its disk kept as a snapshot under the
        session's names. The stopped machine stays until it is released, so
        a snapshot whose record does not land loses nothing: the next
        prepare starts the machine again. `SnapshotRefused` when no machine
        serves the session."""
        ...

    @abstractmethod
    async def release(self, rctx: RequestContext, org_id: UUID, session_id: UUID) -> None:
        """Lets go of the machine that serves the session: its host's
        credential ends and the machine goes, its disk with it."""
        ...

    @abstractmethod
    async def purge(self, org_id: UUID, session_id: UUID) -> None:
        """The session's purge: its machine and every snapshot kept under its
        names go."""
        ...

    @abstractmethod
    async def erase(self, org_id: UUID, session_id: UUID) -> None:
        """The revocation of the session's key: every snapshot kept under its
        names goes. Its machine, a cache, stays."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """A tenant's purge, once it was deleted past its retention: every
        machine that serves one of its sessions goes, and every snapshot
        kept under its names. Answers how many went; a tenant not past its
        retention loses nothing."""
        ...

    @abstractmethod
    async def enroll(
        self, rctx: RequestContext, key: str, enrollment: Enrollment
    ) -> IssuedCredential:
        """A machine's host trades its key, once, for a credential of its
        session's pool of one. `MachineUnbound` while the machine is warm,
        and serves no session yet; `InvalidCredential` for a key never
        handed, or spent."""
        ...

    @abstractmethod
    async def sweep(self, rctx: RequestContext) -> int:
        """One pass: lets go of a machine whose start died with the process
        that started it, of one whose host never came, and of one under the
        pool's names that no row holds; then starts warm machines until the
        pool's warm count stands. Answers how many it let go."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Waits out the warm starts this process began."""
        ...
