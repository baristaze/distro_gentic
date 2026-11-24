"""The cloud pool: one VM per session that runs in the
platform's cloud, through the VMs' backend. Each VM runs the same
host program a customer installs: it trades the key it was handed at its
start for a host's credential of its session's pool of one, claims that
session's work alone through the relay, and holds no credential of the
platform's. The pool keeps no disk of any VM: a session kept by
snapshots keeps its workspace's files, archived as sealed parts in the
snapshots bucket by the platform's tools, and its next loop's VM starts
from the pool's image and takes them back (ADR 2070). The pool records
each session whose files are archived, so the sweep removes them once
the session has been idle past the pool's bound."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.infra.agent_workspaces import AgentWorkspace, IsolationSpec
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
    @stageless
    async def check(self, spec: IsolationSpec) -> None:
        """System-internal: whether the pool's VMs can ever hold a session's
        spec, asked of the spec alone before its loop's first model call.
        `IsolationRefused` that never clears, its cause the spec's, for one
        they never can: a size the deployment does not allow among them, an
        ask of CPUs or memory, an egress the VMs cannot close, or a base. No
        VM starts, and nothing is counted."""
        ...

    @abstractmethod
    async def prepare(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: UUID | None = None,
    ) -> AgentWorkspace:
        """The session's workspace on its VM, once the VM's host
        holds it. The VM is the one that serves the session, else a
        warm one it claims at the default size, one that runs before one
        asleep, which wakes under a fresh key, else one of the size the
        spec asks, started from the pool's image: every VM starts from it.
        With `restore`, the id of the snapshot whose directory the caller
        brings into the workspace, a VM that serves the session for any
        other goes first, since a restore replaces it whole, and the one
        that serves it next is marked for that snapshot, so a prepare asked
        again for it, while its VM starts, keeps it. A new VM, or a warm
        one claimed, counts against the most the
        pool holds and the most the session's tenant holds, as the pool's
        limits stand at this claim; at the pool's maximum, a new one takes
        the place of an idle warm VM, which goes. `IsolationRefused` that
        clears while either maximum stands, the VM starts, or its host has
        not prepared it in time, and the loop waits on the resource; its
        cause names no count and no other tenant's use. One that never
        clears, as `check` refuses it, before any VM starts. Each claim
        counts once, by how it got its VM: a warm one, a hibernated one, a
        new one, the one the session held, or that one started again. A prepare asked again
        before this process's claim returned its workspace is that claim,
        and counts none."""
        ...

    @abstractmethod
    async def archived(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        """Records, before the run's end archives the session's workspace
        files, that the session keeps archives: from now, the sweep holds
        them to the session's last activity. A record that lands before an
        archive that does not keep one removes nothing kept."""
        ...

    @abstractmethod
    async def holds(self, ctx: TenantContext, agent_session_id: UUID) -> bool:
        """Whether a VM of the pool serves the session."""
        ...

    @abstractmethod
    async def recycle(self, ctx: TenantContext, agent_session_id: UUID) -> bool:
        """Between runs, once the run's end kept the session's work: lets
        go of the VM that serves the session if it is past the pool's
        maximum age, as `release` does, and answers whether it went. The
        session's next prepare starts another. Nothing else lets go of a
        session's VM for its age, so none goes under a running loop."""
        ...

    @abstractmethod
    async def release(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        """Lets go of the VM that serves the session: its host's
        credential ends and the VM goes, its disk with it. No image of it
        is kept."""
        ...

    @abstractmethod
    @stageless
    async def purge(self, org_id: UUID, agent_session_id: UUID) -> None:
        """System-internal: the session's purge, which runs for no
        principal: its VM goes, and the record of its archives, whose
        bytes the session's purge takes from the bucket."""
        ...

    @abstractmethod
    @stageless
    async def erase(self, org_id: UUID, agent_session_id: UUID) -> None:
        """System-internal: the revocation of the session's key, named with
        its tenant: the record of its archives goes, in any process, since
        their bytes are noise and leave the bucket with the revocation. Its
        VM, a cache, stays: nothing the pool keeps outside the seal holds
        the session's files."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """A tenant's purge, once it was deleted past its retention: every
        VM that serves one of its sessions goes, the records of its
        sessions' archives, and its own maximum. Answers how many went; a
        tenant not past its retention loses nothing."""
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
        never handed, spent, or ended, as a VM's is before it sleeps."""
        ...

    @abstractmethod
    @transition
    async def sweep(self, rctx: RequestContext) -> int:
        """System-internal: one pass of the sweep, across tenants and for
        none. First the archives, a page at a time: a session idle past the
        pool's `archive_kept`, by its last activity, loses its archives and
        their record; one active since has its record moved to then. Then
        every VM the pool holds, a page at a time, where this process
        reaches the VMs: lets go of a VM whose first start died
        with the process that started it, of one that ran and is gone, of
        one whose session, or tenant, is gone, and of one under the pool's
        names that no row holds; stops a session's VM that runs with no
        host to work for, its host never enrolled, ended, or silent, and
        keeps its disk; lets go of a warm VM past the pool's maximum age,
        and of no session's; hibernates a warm VM started to sleep once it
        settled, its key ended first, and lets go of one asleep before the
        longest its VMs keep one so; then starts warm VMs until the pool's
        warm counts stand, running and hibernated, never past its
        maximum. A warm VM's row goes before
        its VM, so a session that claimed it meanwhile keeps it. Answers how
        many sessions' archives it removed and how many VMs it let go or
        stopped."""
        ...

    @abstractmethod
    @stageless
    async def commanded(self, agent_session_id: UUID) -> None:
        """System-internal: a command starts on the session's workspace,
        which the transport says before it sends it. The first since this
        process's claim of the session's VM records how long the claim
        waited for it; any other records nothing."""
        ...

    @abstractmethod
    @stageless
    async def close(self) -> None:
        """System-internal: at shutdown, waits out the warm starts this
        process began."""
        ...
