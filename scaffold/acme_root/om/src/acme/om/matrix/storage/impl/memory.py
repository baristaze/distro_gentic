from datetime import datetime
from uuid import UUID

from acme.om.base import EMPTY_UUID
from acme.om.exceptions import PreconditionFailed
from acme.om.matrix.storage import MatrixStorageInterface, MatrixTenantStorageInterface
from acme.om.matrix.types.matrix import MatrixStatus, MatrixVersion
from acme.om.matrix.types.record import BenchmarkResult, ModelRef, Retirement
from acme.om.matrix.types.tenant import FillOverride, MatrixPin
from acme.om.models.types.fill import ModelRole
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class MatrixStorageMemoryImpl(MemoryStorageBase, MatrixStorageInterface):
    """The global rows under the system scope's id, as no tenant's."""

    def __init__(self) -> None:
        super().__init__()
        self._versions: MemoryTable[MatrixVersion] = {}
        self._results: MemoryTable[BenchmarkResult] = {}
        self._retirements: MemoryTable[Retirement] = {}

    async def create_version(self, version: MatrixVersion) -> None:
        async with self._lock:
            if any(v.number == version.number for v in self._every(self._versions)):
                raise PreconditionFailed(f"matrix version {version.number} is written already")
            self._insert(self._versions, EMPTY_UUID, version)

    async def read_version(self, number: int) -> MatrixVersion | None:
        return next((v for v in self._every(self._versions) if v.number == number), None)

    async def read_latest(self, status: MatrixStatus | None) -> MatrixVersion | None:
        found = [v for v in self._every(self._versions) if status is None or v.status is status]
        return max(found, key=lambda v: v.number, default=None)

    async def publish_version(
        self, number: int, published_at: datetime, published_by: UUID
    ) -> MatrixVersion | None:
        async with self._lock:
            found = await self.read_version(number)
            later = await self.read_latest(MatrixStatus.PUBLISHED)
            if found is None or found.status is not MatrixStatus.PENDING:
                return None
            if later is not None and later.number > number:
                return None
            published = found.model_copy(
                update={
                    "status": MatrixStatus.PUBLISHED,
                    "published_at": published_at,
                    "published_by": published_by,
                }
            )
            self._put(self._versions, EMPTY_UUID, published)
            return published

    async def add_result(self, result: BenchmarkResult) -> None:
        async with self._lock:
            self._insert(self._results, EMPTY_UUID, result)

    async def read_results(self, model: ModelRef, limit: int) -> list[BenchmarkResult]:
        found = [r for r in self._every(self._results) if r.ref == model]
        return sorted(found, key=lambda r: (r.created_at, r.id), reverse=True)[:limit]

    async def add_retirement(self, retirement: Retirement) -> Retirement:
        async with self._lock:
            held = next(
                (r for r in self._every(self._retirements) if r.ref == retirement.ref), None
            )
            if held is not None:
                return held
            self._insert(self._retirements, EMPTY_UUID, retirement)
            return retirement

    async def read_retirements(self, limit: int) -> list[Retirement]:
        found = self._every(self._retirements)
        return sorted(found, key=lambda r: (r.created_at, r.id), reverse=True)[:limit]


class MatrixTenantStorageMemoryImpl(MemoryStorageBase, MatrixTenantStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._pins: MemoryTable[MatrixPin] = {}
        self._overrides: MemoryTable[FillOverride] = {}

    async def write_pin(self, org_id: UUID, pin: MatrixPin) -> MatrixPin:
        async with self._lock:
            held = next(
                (
                    p
                    for p in self._rows(self._pins, org_id)
                    if p.session_id == pin.session_id and p.fill_set_version == pin.fill_set_version
                ),
                None,
            )
            if held is not None:
                return held
            if not self._insert(self._pins, org_id, pin):
                stored = self._get(self._pins, org_id, pin.id)
                if stored is None:
                    raise PreconditionFailed(f"matrix pin {pin.id} is another tenant's")
                return stored
            return pin

    async def read_pin(self, org_id: UUID, session_id: UUID) -> MatrixPin | None:
        found = [p for p in self._rows(self._pins, org_id) if p.session_id == session_id]
        return max(found, key=lambda p: p.fill_set_version, default=None)

    async def write_override(self, org_id: UUID, override: FillOverride) -> FillOverride:
        async with self._lock:
            held = next(
                (o for o in self._rows(self._overrides, org_id) if o.role == override.role), None
            )
            if held is not None:
                stored = held.model_copy(
                    update={
                        "fill": override.fill,
                        "updated_at": override.updated_at,
                        "updated_by": override.updated_by,
                    }
                )
                self._put(self._overrides, org_id, stored)
                return stored
            self._put(self._overrides, org_id, override)
            return override

    async def delete_override(self, org_id: UUID, role: ModelRole) -> bool:
        async with self._lock:
            held = next((o for o in self._rows(self._overrides, org_id) if o.role == role), None)
            if held is None:
                return False
            del self._overrides[held.id]
            return True

    async def read_overrides(self, org_id: UUID, limit: int) -> list[FillOverride]:
        return sorted(self._rows(self._overrides, org_id), key=lambda o: o.role)[:limit]

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            pins = [pin.id for pin in self._rows(self._pins, org_id)][:limit]
            for pin_id in pins:
                del self._pins[pin_id]
            choices = [o.id for o in self._rows(self._overrides, org_id)][: limit - len(pins)]
            for choice_id in choices:
                del self._overrides[choice_id]
            return len(pins) + len(choices)
