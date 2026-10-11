"""Storage of the cloud pool swimlane: one row per machine the pool started,
in the platform's own table, since a warm machine names no tenant. A row is
written before its machine starts and deleted once its machine is gone, so
a machine under the pool's names with no row is one nobody holds."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.cloud_pool.types.machine import PoolMachine


class CloudPoolStorageInterface(ABC):
    @abstractmethod
    async def create_machine(self, machine: PoolMachine) -> None: ...

    @abstractmethod
    async def reserve_warm(self, wanted: int, made: Sequence[PoolMachine]) -> list[PoolMachine]:
        """Writes as many of `made`, in order, as keep `wanted` warm machines
        standing or starting, and answers those written: one process at a
        time counts and writes, so two sweeps never start one machine
        twice."""
        ...

    @abstractmethod
    async def read_machine(self, machine_id: UUID) -> PoolMachine | None: ...

    @abstractmethod
    async def read_by_key(self, key_digest: str) -> PoolMachine | None:
        """The machine handed the key whose digest this is, until its host
        traded it."""
        ...

    @abstractmethod
    async def read_of_session(self, org_id: UUID, session_id: UUID) -> PoolMachine | None:
        """The machine that serves the session; None when none does."""
        ...

    @abstractmethod
    async def read_of_tenant(self, org_id: UUID, limit: int) -> list[PoolMachine]: ...

    @abstractmethod
    async def read_machines(self, limit: int) -> list[PoolMachine]:
        """Every machine the pool holds, oldest first, at most `limit`."""
        ...

    @abstractmethod
    async def claim_warm(
        self,
        org_id: UUID,
        session_id: UUID,
        pool_id: UUID,
        bound_by: UUID,
        egress_open: bool,
    ) -> PoolMachine | None:
        """Binds one started warm machine of the egress asked to the
        session, and answers it; None when none stands. Two claims never
        take one machine."""
        ...

    @abstractmethod
    async def mark_started(self, machine_id: UUID, at: datetime) -> None: ...

    @abstractmethod
    async def spend_key(self, machine_id: UUID, key_digest: str) -> bool:
        """Spends the machine's key, once: False when it was spent already,
        or another key was handed since."""
        ...

    @abstractmethod
    async def mark_enrolled(self, machine_id: UUID, host_id: UUID) -> None: ...

    @abstractmethod
    async def mark_sealed(self, machine_id: UUID, at: datetime) -> None: ...

    @abstractmethod
    async def rekey(
        self, machine_id: UUID, key_digest: str, restored_from: UUID | None
    ) -> PoolMachine | None:
        """A machine started again under a new key: its host is to enroll
        anew, it is not started and not sealed yet. None once it is gone."""
        ...

    @abstractmethod
    async def delete_machine(self, machine_id: UUID) -> None: ...
