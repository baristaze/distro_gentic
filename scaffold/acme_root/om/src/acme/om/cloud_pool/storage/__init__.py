"""Storage of the cloud pool swimlane: one row per VM the pool started,
in the platform's own table, since a warm VM names no tenant. A row is
written before its VM starts and deleted once its VM is gone, so
a VM under the pool's names with no row is one nobody holds; a warm
VM's row goes first, so no claim binds a VM being destroyed. Beside
them, one row per session whose workspace files the pool archived, with
when it last did, until the archives go, the pool's own limits, and a
tenant's own maximum. Every write that adds a VM
to a count or binds one counts and writes one at a time across
processes, so no maximum is passed."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.cloud_pool.types.archive import PoolArchive
from acme.om.cloud_pool.types.limits import Full, PoolLimits, TenantPoolLimit
from acme.om.cloud_pool.types.vm import PoolClaim, PoolVm
from acme.om.context import tenantless


class CloudPoolStorageInterface(ABC):
    @abstractmethod
    @tenantless
    async def create_vm(self, vm: PoolVm) -> None:
        """Global: a VM's row, written before the VM
        starts. `UniqueKeyTaken` for a name or a key another holds."""
        ...

    @abstractmethod
    @tenantless
    async def claim(
        self, vm: PoolVm, *, most: int, tenant_most: int, warm: bool
    ) -> PoolClaim | Full:
        """Global: the VM that serves `vm`'s session, counted and written
        one claim at a time across processes. `Full.TENANT` while its
        tenant holds `tenant_most` VMs; else, with `warm`, a started warm
        VM of its egress that runs, else a hibernated one, which takes
        `vm`'s key digest, the key it is handed as it wakes; either bound
        to its session, pool, person, and the snapshot it takes back, from
        its `bound_at`. A warm VM started to sleep is taken only once it
        sleeps. Else `vm`'s own row, written before its VM starts.
        While the pool holds `most`, that row takes the place of the
        oldest started warm VM no session claimed, whose row goes and
        which the claim names as displaced, so its VM goes after;
        `Full.POOL` where none stands. `UniqueKeyTaken` for a name or a
        key another holds."""
        ...

    @abstractmethod
    @tenantless
    async def reserve_warm(
        self, wanted: int, most: int, made: Sequence[PoolVm], *, hibernates: bool = False
    ) -> int:
        """Global: writes the first of `made`, in order, as many as
        keep `wanted` warm VMs of its kind standing, starting, or asleep,
        those started to sleep with `hibernates` and those that run
        without, and the pool's VMs no more than `most`, and answers how
        many it wrote: one process at a time counts and writes, so two
        sweeps never start one VM twice and no claim passes the maximum
        beside them."""
        ...

    @abstractmethod
    @tenantless
    async def take_warm(self, vm_id: UUID) -> bool:
        """Global: deletes a warm VM's row, under the lock its claims take,
        while no session has claimed it: False once one has, or it is gone.
        Its VM is destroyed only after, so no claim binds a VM being
        destroyed."""
        ...

    @abstractmethod
    @tenantless
    async def take_to_sleep(self, vm_id: UUID, key_digest: str) -> bool:
        """Global: ends the key of a warm VM started to sleep, while no
        session claimed it, it sleeps not yet, and its key is still the one
        whose digest this is: False otherwise. One sweep alone takes it, and
        it then hibernates holding no key that enrolls."""
        ...

    @abstractmethod
    @tenantless
    async def mark_hibernated(self, vm_id: UUID, at: datetime) -> None:
        """Global: the warm VM sleeps from `at`, so a claim may take it;
        none once a session claimed it."""
        ...

    @abstractmethod
    @tenantless
    async def read_vm(self, vm_id: UUID) -> PoolVm | None:
        """Global: a VM by its row's id."""
        ...

    @abstractmethod
    @tenantless
    async def read_by_key(self, key_digest: str) -> PoolVm | None:
        """Global: the VM handed the key whose digest this
        is, until its host traded it."""
        ...

    @abstractmethod
    @tenantless
    async def read_by_name(self, name: str) -> PoolVm | None:
        """Global: the VM under its name in the VMs'
        backend."""
        ...

    @abstractmethod
    @tenantless
    async def read_of_session(self, tenant_id: UUID, agent_session_id: UUID) -> PoolVm | None:
        """Global: the VM that serves the tenant's session;
        None when none does."""
        ...

    @abstractmethod
    @tenantless
    async def read_of_tenant(self, tenant_id: UUID, limit: int) -> list[PoolVm]:
        """Global: every VM that serves one of the tenant's
        sessions, oldest first, at most `limit`, for the tenant's purge."""
        ...

    @abstractmethod
    @tenantless
    async def read_vms(self, limit: int, after: UUID | None = None) -> list[PoolVm]:
        """Global: the VMs the pool holds, in the order of their
        ids, at most `limit` past `after`: the sweep reads them all, a page
        at a time."""
        ...

    @abstractmethod
    @tenantless
    async def mark_started(self, vm_id: UUID, at: datetime) -> None:
        """Global: the VM runs, from `at`."""
        ...

    @abstractmethod
    @tenantless
    async def spend_key(self, vm_id: UUID, key_digest: str) -> bool:
        """Global: spends the VM's key, once: False when it
        was spent already, or another key was handed since."""
        ...

    @abstractmethod
    @tenantless
    async def mark_enrolled(self, vm_id: UUID, host_id: UUID) -> None:
        """Global: the host that traded the VM's key."""
        ...

    @abstractmethod
    @tenantless
    async def mark_sealed(self, vm_id: UUID, at: datetime) -> None:
        """Global: nothing reads the VM's seed from outside
        it, from `at`."""
        ...

    @abstractmethod
    @tenantless
    async def rekey(self, vm_id: UUID, key_digest: str, at: datetime) -> PoolVm | None:
        """Global: a VM started again under a new key from `at`:
        its host is to enroll anew, and it is not sealed yet. It keeps when
        it first ran, since its disk is the one it ran on. None once it is
        gone."""
        ...

    @abstractmethod
    @tenantless
    async def delete_vm(self, vm_id: UUID) -> None:
        """Global: the row of a VM that is gone."""
        ...

    @abstractmethod
    @tenantless
    async def keep_archive(self, archive: PoolArchive) -> None:
        """Global: the session's archives were kept, or its session was
        active, at `archive.kept_at`: its row made, or moved to then."""
        ...

    @abstractmethod
    @tenantless
    async def read_archives(self, before: datetime, limit: int) -> list[PoolArchive]:
        """Global: the rows kept before `before`, oldest first, at most
        `limit`."""
        ...

    @abstractmethod
    @tenantless
    async def delete_archive(self, tenant_id: UUID, agent_session_id: UUID) -> None:
        """Global: the session's row, once its archives went; none is no
        error."""
        ...

    @abstractmethod
    @tenantless
    async def delete_tenant_archives(self, tenant_id: UUID) -> int:
        """Global: every row of the tenant's sessions; answers how many
        went."""
        ...

    @abstractmethod
    @tenantless
    async def read_limits(self) -> PoolLimits | None:
        """Global: the pool's own limits; None where no operator wrote
        them."""
        ...

    @abstractmethod
    @tenantless
    async def write_limits(self, limits: PoolLimits, version: int | None) -> PoolLimits:
        """Global: the pool's own limits, written over `version`, or first
        with None. `PreconditionFailed` when another write landed since."""
        ...

    @abstractmethod
    async def read_tenant_limit(self, org_id: UUID) -> TenantPoolLimit | None:
        """The tenant's own maximum; None where no operator set one."""
        ...

    @abstractmethod
    async def write_tenant_limit(
        self, org_id: UUID, limit: TenantPoolLimit, version: int | None
    ) -> TenantPoolLimit:
        """The tenant's own maximum, written over `version`, or first with
        None. `PreconditionFailed` when another write landed since."""
        ...

    @abstractmethod
    async def delete_tenant_limit(self, org_id: UUID) -> TenantPoolLimit | None:
        """The tenant's own maximum gone, which it answers; None where it
        had none. Its tenant's purge takes it too."""
        ...
