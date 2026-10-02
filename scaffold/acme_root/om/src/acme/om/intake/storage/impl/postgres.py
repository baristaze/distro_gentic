from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.storage.tables.account_links import AccountLinks
from acme.om.intake.storage.tables.work_bindings import WorkBindings
from acme.om.intake.types.link import AccountLink, HandleKind, WorkBinding
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_values


class IntakeStoragePostgresImpl(PgStorageBase, IntakeStorageInterface):
    async def create_link(self, org_id: UUID, link: AccountLink) -> AccountLink:
        # One link an account: the unique index decides, and a second link
        # of the same account answers the first.
        stmt = (
            insert(AccountLinks)
            .values(**to_values(link, AccountLinks), org_id=org_id)
            .on_conflict_do_nothing(
                index_elements=[
                    AccountLinks.org_id,
                    AccountLinks.integration,
                    AccountLinks.external_id,
                ]
            )
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()
        held = await self.read_link(org_id, link.integration, link.external_id)
        if held is None:
            raise RuntimeError(f"account link {link.id} is not readable after its write")
        return held

    async def read_link(
        self, org_id: UUID, integration: str, external_id: str
    ) -> AccountLink | None:
        stmt = select(AccountLinks).where(
            AccountLinks.org_id == org_id,
            AccountLinks.integration == integration,
            AccountLinks.external_id == external_id,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AccountLink)

    async def create_binding(self, org_id: UUID, binding: WorkBinding) -> WorkBinding:
        stmt = (
            insert(WorkBindings)
            .values(**to_values(binding, WorkBindings), org_id=org_id)
            .on_conflict_do_nothing(
                index_elements=[WorkBindings.org_id, WorkBindings.kind, WorkBindings.handle]
            )
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()
        held = await self.read_binding(org_id, binding.kind, binding.handle)
        if held is None:
            raise RuntimeError(f"work binding {binding.id} is not readable after its write")
        return held

    async def read_binding(self, org_id: UUID, kind: HandleKind, handle: str) -> WorkBinding | None:
        stmt = select(WorkBindings).where(
            WorkBindings.org_id == org_id,
            WorkBindings.kind == kind.value,
            WorkBindings.handle == handle,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, WorkBinding)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        gone = 0
        for table in (AccountLinks, WorkBindings):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                gone += deleted(await session.execute(stmt))
                await session.commit()
        return gone
