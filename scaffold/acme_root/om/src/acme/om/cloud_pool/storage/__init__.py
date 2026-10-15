"""Storage of the cloud pool swimlane: one row per VM the pool started,
in the platform's own table, since a warm VM names no tenant. A row is
written before its VM starts and deleted once its VM is gone, so
a VM under the pool's names with no row is one nobody holds. Beside
them, one row per erasure the pool owes, until the sweep has done it."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.cloud_pool.types.erasure import PoolErasure
from acme.om.cloud_pool.types.vm import PoolVm
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
    async def reserve_warm(self, wanted: int, made: Sequence[PoolVm]) -> int:
        """Global: writes the first of `made`, in order, as many as
        keep `wanted` warm VMs standing or starting, and answers how
        many it wrote: one process at a time counts and writes, so two
        sweeps never start one VM twice."""
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
    async def claim_warm(
        self,
        tenant_id: UUID,
        agent_session_id: UUID,
        pool_id: UUID,
        bound_by: UUID,
        egress_open: bool,
        at: datetime,
    ) -> PoolVm | None:
        """Global: binds one started warm VM of the egress
        asked to the tenant's session from `at`, and answers it; None when
        none stands. Two claims never take one VM."""
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
    async def rekey(
        self, vm_id: UUID, key_digest: str, restored_from: UUID | None, at: datetime
    ) -> PoolVm | None:
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
    async def ask_erase(self, erasure: PoolErasure) -> PoolErasure:
        """Global: a session's disks are to go. Answers the erasure
        that stands for the session: this one, or one asked before it, which
        stands as it is."""
        ...

    @abstractmethod
    @tenantless
    async def read_erasures(self, limit: int) -> list[PoolErasure]:
        """Global: the erasures asked and not done yet, oldest
        first, at most `limit`."""
        ...

    @abstractmethod
    @tenantless
    async def delete_erasure(self, erasure_id: UUID) -> None:
        """Global: an erasure done."""
        ...
