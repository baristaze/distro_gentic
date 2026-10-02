from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update

from acme.om.base import EMPTY_UUID
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.relay.storage import RelayStorageInterface
from acme.om.relay.storage.tables.exec_controls import ExecControls
from acme.om.relay.storage.tables.exec_items import ExecItems
from acme.om.relay.storage.tables.exec_parts import ExecParts
from acme.om.relay.storage.tables.workspace_bindings import WorkspaceBindings
from acme.om.relay.types.exec import (
    ExecControl,
    ExecItem,
    ExecPart,
    ExecState,
    WorkspaceBinding,
)
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values

PURGED_IN_ORDER = (ExecParts, ExecControls, ExecItems, WorkspaceBindings)
"""The relay's tables, each purged a batch at a time: the parts and the
controls before the items they name."""


class RelayStoragePostgresImpl(PgStorageBase, RelayStorageInterface):
    async def create_item(self, org_id: UUID, item: ExecItem) -> bool:
        return await self._insert(ExecItems, org_id, item)

    async def read_item(self, org_id: UUID, item_id: UUID) -> ExecItem | None:
        stmt = select(ExecItems).where(ExecItems.org_id == org_id, ExecItems.id == item_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, ExecItem)

    async def read_items_by_key(
        self, org_id: UUID, session_id: UUID, key: UUID, limit: int
    ) -> list[ExecItem]:
        stmt = (
            select(ExecItems)
            .where(
                ExecItems.org_id == org_id,
                ExecItems.session_id == session_id,
                ExecItems.key == key,
            )
            .order_by(ExecItems.created_at, ExecItems.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, ExecItem) for row in rows]

    async def write_item(
        self, org_id: UUID, item: ExecItem, expected_version: int
    ) -> ExecItem | None:
        values = {k: v for k, v in to_values(item, ExecItems).items() if k != "id"}
        # The version is in the WHERE, so of two writers from one read only
        # the first lands: a host's push, a stop, and the sweep race here.
        stmt = (
            update(ExecItems)
            .where(
                ExecItems.org_id == org_id,
                ExecItems.id == item.id,
                ExecItems.version == expected_version,
            )
            .values(**values)
            .returning(ExecItems)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                await session.rollback()
                return None
            written = to_model(row, ExecItem)
            await session.commit()
            return written

    async def read_expired(self, now: datetime, limit: int) -> list[tuple[UUID, ExecItem]]:
        stmt = (
            select(ExecItems)
            .where(ExecItems.state == ExecState.RUNNING.value, ExecItems.lease_expires_at < now)
            .order_by(ExecItems.lease_expires_at)
            .limit(limit)
        )
        # Every tenant's running items, so the system scope, spelled here.
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [(row.org_id, to_model(row, ExecItem)) for row in rows]

    async def add_part(self, org_id: UUID, part: ExecPart) -> bool:
        try:
            return await self._insert(ExecParts, org_id, part)
        except UniqueKeyTaken:
            # The place is taken under another id: the same part, sent again.
            return False

    async def read_parts(
        self, org_id: UUID, row_id: UUID, after_seq: int, limit: int
    ) -> list[ExecPart]:
        stmt = (
            select(ExecParts)
            .where(
                ExecParts.org_id == org_id, ExecParts.row_id == row_id, ExecParts.seq > after_seq
            )
            .order_by(ExecParts.seq)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, ExecPart) for row in rows]

    async def add_control(
        self, org_id: UUID, control: ExecControl, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        await self._insert(ExecControls, org_id, control, outbox_rows)

    async def read_controls(
        self, org_id: UUID, host_id: UUID, after: UUID | None, since: datetime, limit: int
    ) -> list[ExecControl]:
        stmt = select(ExecControls).where(
            ExecControls.org_id == org_id,
            ExecControls.host_id == host_id,
            ExecControls.created_at >= since,
        )
        if after is not None:
            stmt = stmt.where(ExecControls.id > after)
        stmt = stmt.order_by(ExecControls.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, ExecControl) for row in rows]

    async def write_binding(
        self,
        org_id: UUID,
        binding: WorkspaceBinding,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        stale = PreconditionFailed(
            f"the workspace binding of session {binding.session_id} is no longer at "
            f"version {expected_version}"
        )
        if expected_version == 0:
            try:
                created = await self._insert(WorkspaceBindings, org_id, binding, outbox_rows)
            except UniqueKeyTaken as error:
                raise stale from error
            if not created:
                raise stale
            return
        values = {k: v for k, v in to_values(binding, WorkspaceBindings).items() if k != "id"}
        stmt = (
            update(WorkspaceBindings)
            .where(
                WorkspaceBindings.org_id == org_id,
                WorkspaceBindings.id == binding.id,
                WorkspaceBindings.session_id == binding.session_id,
                WorkspaceBindings.version == expected_version,
            )
            .values(**values)
            .returning(WorkspaceBindings.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                raise stale
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()

    async def read_binding(self, org_id: UUID, session_id: UUID) -> WorkspaceBinding | None:
        stmt = select(WorkspaceBindings).where(
            WorkspaceBindings.org_id == org_id, WorkspaceBindings.session_id == session_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, WorkspaceBinding)

    async def purge_session(self, org_id: UUID, session_id: UUID, limit: int) -> int:
        purged = 0
        for table in PURGED_IN_ORDER:
            stmt = delete_batch(
                table, table.org_id == org_id, table.session_id == session_id, limit=limit
            )
            async with self._session_for(stmt, org_id=org_id) as session:
                purged += deleted(await session.execute(stmt))
                await session.commit()
        return purged

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        purged = 0
        for table in PURGED_IN_ORDER:
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                purged += deleted(await session.execute(stmt))
                await session.commit()
        return purged
