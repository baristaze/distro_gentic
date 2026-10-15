from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from acme.om.base import EMPTY_UUID
from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.storage.tables.identity_links import IdentityLinks
from acme.om.intake.storage.tables.installations import Installations
from acme.om.intake.storage.tables.platform_acts import PlatformActs
from acme.om.intake.storage.tables.work_bindings import WorkBindings
from acme.om.intake.types.link import (
    HandleKind,
    IdentityLink,
    Installation,
    PlatformAct,
    WorkBinding,
)
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_values


class IntakeStoragePostgresImpl(PgStorageBase, IntakeStorageInterface):
    async def create_installation(
        self, org_id: UUID, installation: Installation
    ) -> Installation | None:
        # One tenant an installation: the unique index spans every tenant, so
        # a second tenant's write does nothing, and its read finds no row.
        stmt = (
            insert(Installations)
            .values(**to_values(installation, Installations), org_id=org_id)
            .on_conflict_do_nothing(
                index_elements=[Installations.integration, Installations.installation]
            )
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()
        read = select(Installations).where(
            Installations.org_id == org_id,
            Installations.integration == installation.integration,
            Installations.installation == installation.installation,
        )
        async with self._session_for(read, org_id=org_id) as session:
            row = (await session.execute(read)).scalar_one_or_none()
            return None if row is None else to_model(row, Installation)

    async def read_installation_org(self, integration: str, installation: str) -> UUID | None:
        stmt = select(Installations.org_id).where(
            Installations.integration == integration,
            Installations.installation == installation,
        )
        # Every tenant's installations, so the system scope, spelled here.
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return (await session.execute(stmt)).scalar_one_or_none()

    async def create_link(self, org_id: UUID, link: IdentityLink) -> IdentityLink:
        # One link an account: the unique index decides, and a second link
        # of the same account answers the first.
        stmt = (
            insert(IdentityLinks)
            .values(**to_values(link, IdentityLinks), org_id=org_id)
            .on_conflict_do_nothing(
                index_elements=[
                    IdentityLinks.org_id,
                    IdentityLinks.integration,
                    IdentityLinks.external_id,
                ]
            )
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()
        held = await self.read_link(org_id, link.integration, link.external_id)
        if held is None:
            raise RuntimeError(f"identity link {link.id} is not readable after its write")
        return held

    async def read_link(
        self, org_id: UUID, integration: str, external_id: str
    ) -> IdentityLink | None:
        stmt = select(IdentityLinks).where(
            IdentityLinks.org_id == org_id,
            IdentityLinks.integration == integration,
            IdentityLinks.external_id == external_id,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, IdentityLink)

    async def read_user_links(self, org_id: UUID, user_id: UUID, limit: int) -> list[IdentityLink]:
        stmt = (
            select(IdentityLinks)
            .where(IdentityLinks.org_id == org_id, IdentityLinks.user_id == user_id)
            .order_by(IdentityLinks.integration, IdentityLinks.external_id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, IdentityLink) for row in rows]

    async def delete_link(self, org_id: UUID, integration: str, external_id: str) -> bool:
        stmt = delete(IdentityLinks).where(
            IdentityLinks.org_id == org_id,
            IdentityLinks.integration == integration,
            IdentityLinks.external_id == external_id,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone > 0

    async def delete_user_links(self, org_id: UUID, user_id: UUID, ids: Sequence[UUID]) -> int:
        stmt = delete(IdentityLinks).where(
            IdentityLinks.org_id == org_id,
            IdentityLinks.user_id == user_id,
            IdentityLinks.id.in_(ids),
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone

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

    async def read_session_bindings(
        self, org_id: UUID, agent_session_id: UUID, limit: int
    ) -> list[WorkBinding]:
        stmt = (
            select(WorkBindings)
            .where(WorkBindings.org_id == org_id, WorkBindings.agent_session_id == agent_session_id)
            .order_by(WorkBindings.created_at, WorkBindings.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, WorkBinding) for row in rows]

    async def record_act(self, org_id: UUID, act: PlatformAct) -> None:
        # One act a name: the unique index decides, and the latest holds.
        stmt = (
            insert(PlatformActs)
            .values(**to_values(act, PlatformActs), org_id=org_id)
            .on_conflict_do_update(
                index_elements=[PlatformActs.org_id, PlatformActs.integration, PlatformActs.ref],
                set_={
                    "id": act.id,
                    "created_at": act.created_at,
                    "agent_session_id": act.agent_session_id,
                },
            )
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()

    async def read_act(
        self, org_id: UUID, integration: str, refs: Sequence[str]
    ) -> PlatformAct | None:
        if not refs:
            return None
        stmt = (
            select(PlatformActs)
            .where(
                PlatformActs.org_id == org_id,
                PlatformActs.integration == integration,
                PlatformActs.ref.in_(list(refs)),
            )
            .order_by(PlatformActs.created_at.desc(), PlatformActs.id.desc())
            .limit(1)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, PlatformAct)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        gone = 0
        for table in (Installations, IdentityLinks, WorkBindings, PlatformActs):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                gone += deleted(await session.execute(stmt))
                await session.commit()
        return gone
