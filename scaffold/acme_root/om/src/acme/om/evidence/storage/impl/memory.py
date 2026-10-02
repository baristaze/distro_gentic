from collections.abc import Callable, Sequence
from uuid import UUID

from acme.om.evidence.storage import EvidenceStorageInterface
from acme.om.evidence.types.inference import Inference
from acme.om.evidence.types.policy import ValidationPolicy
from acme.om.evidence.types.record import ExecutionRecord
from acme.om.evidence.types.validation import Validation
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.memory_base import HasId, MemoryStorageBase, MemoryTable


class EvidenceStorageMemoryImpl(MemoryStorageBase, EvidenceStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._policies: MemoryTable[ValidationPolicy] = {}
        self._records: MemoryTable[ExecutionRecord] = {}
        self._validations: MemoryTable[Validation] = {}
        self._inferences: MemoryTable[Inference] = {}

    # The policies.

    async def read_policy(self, org_id: UUID, project: str) -> ValidationPolicy | None:
        return next(
            (found for found in self._rows(self._policies, org_id) if found.project == project),
            None,
        )

    async def create_policy(
        self, org_id: UUID, policy: ValidationPolicy, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if policy.id in self._policies:
                return False
            # One policy a project: the unique index the table holds.
            if await self.read_policy(org_id, policy.project) is not None:
                raise UniqueKeyTaken(f"validation_policies {policy.id}: the project holds a policy")
            return self._insert(self._policies, org_id, policy, outbox_rows)

    async def write_policy(
        self,
        org_id: UUID,
        policy: ValidationPolicy,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._lock:
            found = self._get(self._policies, org_id, policy.id)
            if found is None or found.version != expected_version:
                raise PreconditionFailed(
                    f"validation policy {policy.id} is no longer at version {expected_version}"
                )
            self._put(self._policies, org_id, policy, outbox_rows)

    # The runs, written once.

    async def create_record(self, org_id: UUID, record: ExecutionRecord) -> bool:
        async with self._lock:
            return self._insert(self._records, org_id, record)

    async def create_validation(
        self, org_id: UUID, validation: Validation, records: Sequence[ExecutionRecord]
    ) -> bool:
        async with self._lock:
            if validation.id in self._validations:
                return False
            taken = [record.id for record in records if record.id in self._records]
            if taken:
                # One commit: a run written already lands none of it.
                raise UniqueKeyTaken(f"execution_records {taken[0]} is written already")
            for record in records:
                self._insert(self._records, org_id, record)
            return self._insert(self._validations, org_id, validation)

    async def create_inference(self, org_id: UUID, inference: Inference) -> bool:
        async with self._lock:
            return self._insert(self._inferences, org_id, inference)

    async def read_records(
        self, org_id: UUID, session_id: UUID, after: UUID | None, limit: int
    ) -> list[ExecutionRecord]:
        return [
            record
            for record in self._rows(self._records, org_id)
            if record.session_id == session_id and (after is None or record.id > after)
        ][:limit]

    async def read_cited(
        self, org_id: UUID, session_id: UUID, ids: Sequence[UUID], limit: int
    ) -> list[ExecutionRecord]:
        wanted = set(ids)
        return [
            record
            for record in self._rows(self._records, org_id)
            if record.session_id == session_id
            and {record.id, record.step_id, record.validation_id} & wanted
        ][:limit]

    async def read_validations(
        self, org_id: UUID, session_id: UUID, version: str | None, limit: int
    ) -> list[Validation]:
        return [
            validation
            for validation in self._rows(self._validations, org_id)
            if validation.session_id == session_id
            and (version is None or validation.version == version)
        ][:limit]

    async def read_validation_records(
        self, org_id: UUID, session_id: UUID, validation_ids: Sequence[UUID], limit: int
    ) -> list[ExecutionRecord]:
        wanted = set(validation_ids)
        return [
            record
            for record in self._rows(self._records, org_id)
            if record.session_id == session_id and record.validation_id in wanted
        ][:limit]

    async def read_inferences(
        self, org_id: UUID, session_id: UUID, after: UUID | None, limit: int
    ) -> list[Inference]:
        return [
            inference
            for inference in self._rows(self._inferences, org_id)
            if inference.session_id == session_id and (after is None or inference.id > after)
        ][:limit]

    async def read_inference(self, org_id: UUID, inference_id: UUID) -> Inference | None:
        return self._get(self._inferences, org_id, inference_id)

    # The purges.

    async def purge_session(self, org_id: UUID, session_id: UUID, limit: int) -> int:
        async with self._lock:
            return (
                self._drop(self._records, org_id, lambda row: row.session_id == session_id, limit)
                + self._drop(
                    self._validations, org_id, lambda row: row.session_id == session_id, limit
                )
                + self._drop(
                    self._inferences, org_id, lambda row: row.session_id == session_id, limit
                )
            )

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            return (
                self._drop(self._policies, org_id, lambda row: True, limit)
                + self._drop(self._records, org_id, lambda row: True, limit)
                + self._drop(self._validations, org_id, lambda row: True, limit)
                + self._drop(self._inferences, org_id, lambda row: True, limit)
            )

    @classmethod
    def _drop[E: HasId](
        cls, table: MemoryTable[E], org_id: UUID, chosen: Callable[[E], bool], limit: int
    ) -> int:
        """At most `limit` of a tenant's rows `chosen` picks, by id, gone."""
        ids = [row.id for row in cls._rows(table, org_id) if chosen(row)][:limit]
        for row_id in ids:
            del table[row_id]
        return len(ids)
