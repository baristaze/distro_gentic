"""Storage of the cloud pool swimlane: one row per machine the pool started,
in the platform's own table, since a warm machine names no tenant. A row is
written before its machine starts and deleted once its machine is gone, so
a machine under the pool's names with no row is one nobody holds. Beside
them, one row per erasure the pool owes, until the sweep has done it."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.cloud_pool.types.erasure import PoolErasure
from acme.om.cloud_pool.types.machine import PoolMachine


class CloudPoolStorageInterface(ABC):
    @abstractmethod
    async def create_machine(self, machine: PoolMachine) -> None:
        """Global: a machine's row, written before the machine
        starts. `UniqueKeyTaken` for a name or a key another holds."""
        ...

    @abstractmethod
    async def reserve_warm(self, wanted: int, made: Sequence[PoolMachine]) -> int:
        """Global: writes the first of `made`, in order, as many as
        keep `wanted` warm machines standing or starting, and answers how
        many it wrote: one process at a time counts and writes, so two
        sweeps never start one machine twice."""
        ...

    @abstractmethod
    async def read_machine(self, machine_id: UUID) -> PoolMachine | None:
        """Global: a machine by its row's id."""
        ...

    @abstractmethod
    async def read_by_key(self, key_digest: str) -> PoolMachine | None:
        """Global: the machine handed the key whose digest this
        is, until its host traded it."""
        ...

    @abstractmethod
    async def read_by_name(self, name: str) -> PoolMachine | None:
        """Global: the machine under its name in the machines'
        backend."""
        ...

    @abstractmethod
    async def read_of_session(self, tenant_id: UUID, session_id: UUID) -> PoolMachine | None:
        """Global: the machine that serves the tenant's session;
        None when none does."""
        ...

    @abstractmethod
    async def read_of_tenant(self, tenant_id: UUID, limit: int) -> list[PoolMachine]:
        """Global: every machine that serves one of the tenant's
        sessions, oldest first, at most `limit`, for the tenant's purge."""
        ...

    @abstractmethod
    async def read_machines(self, limit: int, after: UUID | None = None) -> list[PoolMachine]:
        """Global: the machines the pool holds, in the order of their
        ids, at most `limit` past `after`: the sweep reads them all, a page
        at a time."""
        ...

    @abstractmethod
    async def claim_warm(
        self,
        tenant_id: UUID,
        session_id: UUID,
        pool_id: UUID,
        bound_by: UUID,
        egress_open: bool,
        at: datetime,
    ) -> PoolMachine | None:
        """Global: binds one started warm machine of the egress
        asked to the tenant's session from `at`, and answers it; None when
        none stands. Two claims never take one machine."""
        ...

    @abstractmethod
    async def mark_started(self, machine_id: UUID, at: datetime) -> None:
        """Global: the machine runs, from `at`."""
        ...

    @abstractmethod
    async def spend_key(self, machine_id: UUID, key_digest: str) -> bool:
        """Global: spends the machine's key, once: False when it
        was spent already, or another key was handed since."""
        ...

    @abstractmethod
    async def mark_enrolled(self, machine_id: UUID, host_id: UUID) -> None:
        """Global: the host that traded the machine's key."""
        ...

    @abstractmethod
    async def mark_sealed(self, machine_id: UUID, at: datetime) -> None:
        """Global: nothing reads the machine's seed from outside
        it, from `at`."""
        ...

    @abstractmethod
    async def rekey(
        self, machine_id: UUID, key_digest: str, restored_from: UUID | None, at: datetime
    ) -> PoolMachine | None:
        """Global: a machine started again under a new key from `at`:
        its host is to enroll anew, and it is not sealed yet. It keeps when
        it first ran, since its disk is the one it ran on. None once it is
        gone."""
        ...

    @abstractmethod
    async def delete_machine(self, machine_id: UUID) -> None:
        """Global: the row of a machine that is gone."""
        ...

    @abstractmethod
    async def ask_erase(self, erasure: PoolErasure) -> PoolErasure:
        """Global: a session's disks are to go. Answers the erasure
        that stands for the session: this one, or one asked before it, which
        stands as it is."""
        ...

    @abstractmethod
    async def read_erasures(self, limit: int) -> list[PoolErasure]:
        """Global: the erasures asked and not done yet, oldest
        first, at most `limit`."""
        ...

    @abstractmethod
    async def delete_erasure(self, erasure_id: UUID) -> None:
        """Global: an erasure done."""
        ...
