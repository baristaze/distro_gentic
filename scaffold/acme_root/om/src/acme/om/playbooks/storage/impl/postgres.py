from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.playbooks.storage.tables.playbook_invocations import PlaybookInvocations
from acme.om.playbooks.storage.tables.playbook_pins import PlaybookPins
from acme.om.playbooks.storage.tables.playbooks import Playbooks
from acme.om.playbooks.types.playbook import Playbook, PlaybookInvocation, PlaybookPin
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values


class PlaybookStoragePostgresImpl(PgStorageBase, PlaybookStorageInterface):
    async def create_playbook(
        self, org_id: UUID, playbook: Playbook, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(Playbooks, org_id, playbook, outbox_rows)

    async def read_playbook(self, org_id: UUID, playbook_id: UUID) -> Playbook | None:
        stmt = select(Playbooks).where(Playbooks.org_id == org_id, Playbooks.id == playbook_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Playbook)

    async def read_latest(self, org_id: UUID, name: str) -> Playbook | None:
        stmt = (
            select(Playbooks)
            .where(Playbooks.org_id == org_id, Playbooks.name == name)
            .order_by(Playbooks.version.desc())
            .limit(1)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Playbook)

    async def create_invocation(
        self, org_id: UUID, invocation: PlaybookInvocation
    ) -> PlaybookInvocation:
        stmt = (
            insert(PlaybookInvocations)
            .values(**to_values(invocation, PlaybookInvocations), org_id=org_id)
            .on_conflict_do_nothing(
                index_elements=[
                    PlaybookInvocations.org_id,
                    PlaybookInvocations.session_id,
                    PlaybookInvocations.playbook_id,
                ]
            )
        )
        read = select(PlaybookInvocations).where(
            PlaybookInvocations.org_id == org_id,
            PlaybookInvocations.session_id == invocation.session_id,
            PlaybookInvocations.playbook_id == invocation.playbook_id,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()
        # The fence is the transaction's: the read that answers is a new one.
        async with self._session_for(read, org_id=org_id) as session:
            return to_model((await session.execute(read)).scalar_one(), PlaybookInvocation)

    async def read_invocations(
        self, org_id: UUID, session_id: UUID, limit: int
    ) -> list[PlaybookInvocation]:
        stmt = (
            select(PlaybookInvocations)
            .where(
                PlaybookInvocations.org_id == org_id,
                PlaybookInvocations.session_id == session_id,
            )
            .order_by(PlaybookInvocations.created_at, PlaybookInvocations.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, PlaybookInvocation) for row in rows]

    async def put_pin(
        self, org_id: UUID, pin: PlaybookPin, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        await self._upsert(PlaybookPins, org_id, pin, outbox_rows)

    async def read_pin(
        self, org_id: UUID, kind: str, project_id: UUID | None
    ) -> PlaybookPin | None:
        stmt = select(PlaybookPins).where(
            PlaybookPins.org_id == org_id,
            PlaybookPins.kind == kind,
            PlaybookPins.project_id.is_(None)
            if project_id is None
            else PlaybookPins.project_id == project_id,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, PlaybookPin)

    async def read_pins(self, org_id: UUID, limit: int) -> list[PlaybookPin]:
        stmt = (
            select(PlaybookPins)
            .where(PlaybookPins.org_id == org_id)
            .order_by(
                PlaybookPins.kind,
                PlaybookPins.project_id.is_not(None),
                PlaybookPins.project_id,
            )
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, PlaybookPin) for row in rows]

    async def delete_pin(
        self, org_id: UUID, pin_id: UUID, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        stmt = (
            delete(PlaybookPins)
            .where(PlaybookPins.org_id == org_id, PlaybookPins.id == pin_id)
            .returning(PlaybookPins.id)
        )
        async with self._session_for(PlaybookPins, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                return False
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return True

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        gone = 0
        for table in (PlaybookPins, PlaybookInvocations, Playbooks):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                gone += deleted(await session.execute(stmt))
                await session.commit()
        return gone
