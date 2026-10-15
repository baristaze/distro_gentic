from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update

from acme.om.base import EMPTY_UUID
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.exec_relay.storage import ExecRelayStorageInterface
from acme.om.exec_relay.storage.tables.agent_workspace_bindings import AgentWorkspaceBindings
from acme.om.exec_relay.storage.tables.exec_controls import ExecControls
from acme.om.exec_relay.storage.tables.exec_items import ExecItems
from acme.om.exec_relay.storage.tables.exec_parts import ExecParts
from acme.om.exec_relay.types.exec import (
    AgentWorkspaceBinding,
    ExecControl,
    ExecItem,
    ExecPart,
    ExecState,
)
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values

PURGED_IN_ORDER = (ExecParts, ExecControls, ExecItems, AgentWorkspaceBindings)
"""The exec relay's tables, each purged a batch at a time: the parts and the
controls before the items they name."""


class ExecRelayStoragePostgresImpl(PgStorageBase, ExecRelayStorageInterface):
    async def create_item(self, org_id: UUID, item: ExecItem) -> bool:
        return await self._insert(ExecItems, org_id, item)

    async def read_item(self, org_id: UUID, item_id: UUID) -> ExecItem | None:
        stmt = select(ExecItems).where(ExecItems.org_id == org_id, ExecItems.id == item_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, ExecItem)

    async def read_items_by_key(
        self, org_id: UUID, agent_session_id: UUID, key: UUID, limit: int
    ) -> list[ExecItem]:
        stmt = (
            select(ExecItems)
            .where(
                ExecItems.org_id == org_id,
                ExecItems.agent_session_id == agent_session_id,
                ExecItems.key == key,
            )
            .order_by(ExecItems.created_at, ExecItems.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, ExecItem) for row in rows]

    async def read_running(
        self, org_id: UUID, agent_session_id: UUID, limit: int
    ) -> list[ExecItem]:
        stmt = (
            select(ExecItems)
            .where(
                ExecItems.org_id == org_id,
                ExecItems.agent_session_id == agent_session_id,
                ExecItems.state == ExecState.RUNNING.value,
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
        binding: AgentWorkspaceBinding,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        stale = PreconditionFailed(
            f"the workspace binding of session {binding.agent_session_id} is no longer at "
            f"version {expected_version}"
        )
        if expected_version == 0:
            try:
                created = await self._insert(AgentWorkspaceBindings, org_id, binding, outbox_rows)
            except UniqueKeyTaken as error:
                raise stale from error
            if not created:
                raise stale
            return
        values = {k: v for k, v in to_values(binding, AgentWorkspaceBindings).items() if k != "id"}
        stmt = (
            update(AgentWorkspaceBindings)
            .where(
                AgentWorkspaceBindings.org_id == org_id,
                AgentWorkspaceBindings.id == binding.id,
                AgentWorkspaceBindings.agent_session_id == binding.agent_session_id,
                AgentWorkspaceBindings.version == expected_version,
            )
            .values(**values)
            .returning(AgentWorkspaceBindings.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                raise stale
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()

    async def read_binding(
        self, org_id: UUID, agent_session_id: UUID
    ) -> AgentWorkspaceBinding | None:
        stmt = select(AgentWorkspaceBindings).where(
            AgentWorkspaceBindings.org_id == org_id,
            AgentWorkspaceBindings.agent_session_id == agent_session_id,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentWorkspaceBinding)

    async def read_bindings(
        self, after: UUID | None, limit: int
    ) -> list[tuple[UUID, AgentWorkspaceBinding]]:
        stmt = select(AgentWorkspaceBindings).order_by(AgentWorkspaceBindings.id).limit(limit)
        if after is not None:
            stmt = stmt.where(AgentWorkspaceBindings.id > after)
        # Every tenant's bindings, so the system scope, spelled here.
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [(row.org_id, to_model(row, AgentWorkspaceBinding)) for row in rows]

    async def purge_agent_session(self, org_id: UUID, agent_session_id: UUID, limit: int) -> int:
        purged = 0
        for table in PURGED_IN_ORDER:
            stmt = delete_batch(
                table,
                table.org_id == org_id,
                table.agent_session_id == agent_session_id,
                limit=limit,
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
