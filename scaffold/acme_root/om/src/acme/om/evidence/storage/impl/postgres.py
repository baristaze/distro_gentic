from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from acme.om.evidence.storage import EvidenceStorageInterface
from acme.om.evidence.storage.tables.execution_records import ExecutionRecords
from acme.om.evidence.storage.tables.inferences import Inferences
from acme.om.evidence.storage.tables.validation_policies import ValidationPolicies
from acme.om.evidence.storage.tables.validations import Validations
from acme.om.evidence.types.inference import Inference
from acme.om.evidence.types.policy import ValidationPolicy
from acme.om.evidence.types.record import ExecutionRecord
from acme.om.evidence.types.validation import Validation
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import (
    PgStorageBase,
    delete_batch,
    deleted,
    violated_constraint,
)
from acme.om.storage.utils.translation import to_model, to_row, to_values

WRITTEN_ONCE = (ExecutionRecords, Validations, Inferences)
"""The tables whose rows only the purge login deletes."""


class EvidenceStoragePostgresImpl(PgStorageBase, EvidenceStorageInterface):
    # The policies.

    async def read_policy(self, org_id: UUID, project: str) -> ValidationPolicy | None:
        stmt = select(ValidationPolicies).where(
            ValidationPolicies.org_id == org_id, ValidationPolicies.project == project
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, ValidationPolicy)

    async def create_policy(
        self, org_id: UUID, policy: ValidationPolicy, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(ValidationPolicies, org_id, policy, outbox_rows)

    async def write_policy(
        self,
        org_id: UUID,
        policy: ValidationPolicy,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        values = {
            k: v
            for k, v in to_values(policy, ValidationPolicies).items()
            if k not in ("id", "project")
        }
        # The version is in the WHERE, so two writers from one snapshot
        # cannot both land.
        stmt = (
            update(ValidationPolicies)
            .where(
                ValidationPolicies.id == policy.id,
                ValidationPolicies.org_id == org_id,
                ValidationPolicies.version == expected_version,
            )
            .values(**values)
            .returning(ValidationPolicies.id)
        )
        async with self._session_for(ValidationPolicies, org_id=org_id) as db:
            if (await db.execute(stmt)).scalar_one_or_none() is None:
                await db.rollback()
                raise PreconditionFailed(
                    f"validation policy {policy.id} is no longer at version {expected_version}"
                )
            for outbox_row in outbox_rows:
                db.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await db.commit()

    # The runs, written once.

    async def create_record(self, org_id: UUID, record: ExecutionRecord) -> bool:
        return await self._insert(ExecutionRecords, org_id, record)

    async def create_validation(
        self, org_id: UUID, validation: Validation, records: Sequence[ExecutionRecord]
    ) -> bool:
        async with self._session_for(Validations, org_id=org_id) as session:
            try:
                # The validation first, so a retry meets its key before any
                # run's.
                session.add(to_row(validation, Validations, org_id=org_id))
                await session.flush()
                session.add_all(
                    to_row(record, ExecutionRecords, org_id=org_id) for record in records
                )
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                constraint = violated_constraint(error)
                # The naming convention names the primary key `pk_<table>`.
                if constraint == f"pk_{Validations.__tablename__}":
                    return False
                raise UniqueKeyTaken(
                    f"validation {validation.id}: {constraint or 'a unique key'} is taken"
                ) from error
            return True

    async def create_inference(self, org_id: UUID, inference: Inference) -> bool:
        return await self._insert(Inferences, org_id, inference)

    async def read_records(
        self, org_id: UUID, session_id: UUID, after: UUID | None, limit: int
    ) -> list[ExecutionRecord]:
        stmt = select(ExecutionRecords).where(
            ExecutionRecords.org_id == org_id, ExecutionRecords.session_id == session_id
        )
        if after is not None:
            stmt = stmt.where(ExecutionRecords.id > after)
        return await self._records(org_id, stmt.order_by(ExecutionRecords.id).limit(limit))

    async def read_cited(
        self, org_id: UUID, session_id: UUID, ids: Sequence[UUID], limit: int
    ) -> list[ExecutionRecord]:
        if not ids:
            return []
        named = list(ids)
        stmt = (
            select(ExecutionRecords)
            .where(
                ExecutionRecords.org_id == org_id,
                ExecutionRecords.session_id == session_id,
                or_(
                    ExecutionRecords.id.in_(named),
                    ExecutionRecords.step_id.in_(named),
                    ExecutionRecords.validation_id.in_(named),
                ),
            )
            .order_by(ExecutionRecords.id)
            .limit(limit)
        )
        return await self._records(org_id, stmt)

    async def read_validations(
        self, org_id: UUID, session_id: UUID, version: str | None, limit: int
    ) -> list[Validation]:
        stmt = select(Validations).where(
            Validations.org_id == org_id, Validations.session_id == session_id
        )
        if version is not None:
            stmt = stmt.where(Validations.version == version)
        stmt = stmt.order_by(Validations.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, Validation) for row in rows]

    async def read_validation_records(
        self, org_id: UUID, session_id: UUID, validation_ids: Sequence[UUID], limit: int
    ) -> list[ExecutionRecord]:
        if not validation_ids:
            return []
        stmt = (
            select(ExecutionRecords)
            .where(
                ExecutionRecords.org_id == org_id,
                ExecutionRecords.session_id == session_id,
                ExecutionRecords.validation_id.in_(list(validation_ids)),
            )
            .order_by(ExecutionRecords.id)
            .limit(limit)
        )
        return await self._records(org_id, stmt)

    async def read_inferences(
        self, org_id: UUID, session_id: UUID, after: UUID | None, limit: int
    ) -> list[Inference]:
        stmt = select(Inferences).where(
            Inferences.org_id == org_id, Inferences.session_id == session_id
        )
        if after is not None:
            stmt = stmt.where(Inferences.id > after)
        stmt = stmt.order_by(Inferences.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, Inference) for row in rows]

    async def read_inference(self, org_id: UUID, inference_id: UUID) -> Inference | None:
        stmt = select(Inferences).where(Inferences.org_id == org_id, Inferences.id == inference_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Inference)

    # The purges.

    async def purge_session(self, org_id: UUID, session_id: UUID, limit: int) -> int:
        purged = 0
        async with self._purge_session_for(ExecutionRecords, org_id=org_id) as session:
            for table in WRITTEN_ONCE:
                batch = (
                    select(table.id)
                    .where(table.org_id == org_id, table.session_id == session_id)
                    .limit(limit)
                )
                stmt = delete(table).where(table.org_id == org_id, table.id.in_(batch))
                purged += deleted(await session.execute(stmt))
            await session.commit()
        return purged

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        policies = delete_batch(
            ValidationPolicies, ValidationPolicies.org_id == org_id, limit=limit
        )
        async with self._session_for(policies, org_id=org_id) as session:
            purged = deleted(await session.execute(policies))
            await session.commit()
        async with self._purge_session_for(ExecutionRecords, org_id=org_id) as session:
            for table in WRITTEN_ONCE:
                batch = select(table.id).where(table.org_id == org_id).limit(limit)
                stmt = delete(table).where(table.org_id == org_id, table.id.in_(batch))
                purged += deleted(await session.execute(stmt))
            await session.commit()
        return purged

    async def _records(self, org_id: UUID, stmt: Any) -> list[ExecutionRecord]:
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, ExecutionRecord) for row in rows]
