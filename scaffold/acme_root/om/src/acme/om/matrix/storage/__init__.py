"""Storage of the matrix swimlane. The matrix, the benchmark results, and
the retirements are the platform's own, no tenant's: global rows of the
system scope (`MatrixStorageInterface`). The pins of a tenant's sessions
and its own choices of fill are the tenant's, and every operation on them
takes org_id first (`MatrixTenantStorageInterface`)."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.matrix.types.matrix import MatrixStatus, MatrixVersion
from acme.om.matrix.types.record import BenchmarkResult, ModelRef, Retirement
from acme.om.matrix.types.tenant import FillOverride, MatrixPin
from acme.om.models.types.fill import ModelRole


class MatrixStorageInterface(ABC):
    # The versions.

    @abstractmethod
    async def create_version(self, version: MatrixVersion) -> None:
        """Global: writes a version, once. `PreconditionFailed`, with nothing
        written, when its number is taken."""
        ...

    @abstractmethod
    async def read_version(self, number: int) -> MatrixVersion | None:
        """Global: the version `number`, or None."""
        ...

    @abstractmethod
    async def read_latest(self, status: MatrixStatus | None) -> MatrixVersion | None:
        """Global: the version of the highest number, of `status` when one is
        given; None when there is none."""
        ...

    @abstractmethod
    async def publish_version(
        self, number: int, published_at: datetime, published_by: UUID
    ) -> MatrixVersion | None:
        """Global: marks the pending version `number` published, in one
        statement that also holds no later version is published; None, with
        nothing changed, when it is not pending or a later one is."""
        ...

    # The records.

    @abstractmethod
    async def add_result(self, result: BenchmarkResult) -> None:
        """Global: writes a benchmark result, once; a retry of its id writes
        nothing."""
        ...

    @abstractmethod
    async def read_results(self, model: ModelRef, limit: int) -> list[BenchmarkResult]:
        """Global: the results recorded for `model`, newest first, at most
        `limit`."""
        ...

    @abstractmethod
    async def add_retirement(self, retirement: Retirement) -> Retirement:
        """Global: writes a retirement, once a model; the stored one when the
        model is retired already."""
        ...

    @abstractmethod
    async def read_retirements(self, limit: int) -> list[Retirement]:
        """Global: the retired models, newest first, at most `limit`."""
        ...


class MatrixTenantStorageInterface(ABC):
    @abstractmethod
    async def write_pin(self, org_id: UUID, pin: MatrixPin) -> MatrixPin:
        """Writes the pin of one version of a session's fill set, once: the
        stored one when that version has a pin already."""
        ...

    @abstractmethod
    async def read_pin(self, org_id: UUID, session_id: UUID) -> MatrixPin | None:
        """The pin of the session's latest pinned fill-set version, or None."""
        ...

    @abstractmethod
    async def write_override(self, org_id: UUID, override: FillOverride) -> FillOverride:
        """Writes the tenant's choice for its model role, in place of the one
        it held: answers what is stored."""
        ...

    @abstractmethod
    async def delete_override(self, org_id: UUID, role: ModelRole) -> bool:
        """Takes the tenant's choice for `role` away; False when it held none."""
        ...

    @abstractmethod
    async def read_overrides(self, org_id: UUID, limit: int) -> list[FillOverride]:
        """The tenant's choices, by model role, at most `limit`."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` pins and choices of a deleted tenant past its
        retention; returns how many went."""
        ...
