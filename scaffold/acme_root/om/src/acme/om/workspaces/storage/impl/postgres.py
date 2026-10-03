from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update

from acme.om.exceptions import PreconditionFailed
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values
from acme.om.workspaces.storage import WorkspaceStorageInterface
from acme.om.workspaces.storage.tables.egress_allowlists import EgressAllowlists
from acme.om.workspaces.storage.tables.repository_credentials import RepositoryCredentials
from acme.om.workspaces.storage.tables.session_workspaces import SessionWorkspaces
from acme.om.workspaces.types.credential import RepositoryCredential
from acme.om.workspaces.types.egress import EgressAllowlist
from acme.om.workspaces.types.workspace import SessionWorkspace


class WorkspaceStoragePostgresImpl(PgStorageBase, WorkspaceStorageInterface):
    async def read_workspace(self, org_id: UUID, session_id: UUID) -> SessionWorkspace | None:
        stmt = select(SessionWorkspaces).where(
            SessionWorkspaces.id == session_id, SessionWorkspaces.org_id == org_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, SessionWorkspace)

    async def create_workspace(self, org_id: UUID, workspace: SessionWorkspace) -> bool:
        return await self._insert(SessionWorkspaces, org_id, workspace)

    async def write_workspace(
        self, org_id: UUID, workspace: SessionWorkspace, expected_version: int
    ) -> None:
        values = {k: v for k, v in to_values(workspace, SessionWorkspaces).items() if k != "id"}
        # The version is in the WHERE, so two writers from one snapshot
        # cannot both land.
        stmt = (
            update(SessionWorkspaces)
            .where(
                SessionWorkspaces.id == workspace.id,
                SessionWorkspaces.org_id == org_id,
                SessionWorkspaces.version == expected_version,
            )
            .values(**values)
            .returning(SessionWorkspaces.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                raise PreconditionFailed(
                    f"workspace {workspace.id} is no longer at version {expected_version}"
                )
            await session.commit()

    async def read_allowlist(self, org_id: UUID, project_id: UUID) -> EgressAllowlist | None:
        stmt = select(EgressAllowlists).where(
            EgressAllowlists.org_id == org_id, EgressAllowlists.project_id == project_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, EgressAllowlist)

    async def create_allowlist(
        self, org_id: UUID, allowlist: EgressAllowlist, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(EgressAllowlists, org_id, allowlist, outbox_rows)

    async def write_allowlist(
        self,
        org_id: UUID,
        allowlist: EgressAllowlist,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        values: dict[str, Any] = {
            k: v for k, v in to_values(allowlist, EgressAllowlists).items() if k != "id"
        }
        stmt = (
            update(EgressAllowlists)
            .where(
                EgressAllowlists.id == allowlist.id,
                EgressAllowlists.org_id == org_id,
                EgressAllowlists.version == expected_version,
            )
            .values(**values)
            .returning(EgressAllowlists.id)
        )
        async with self._session_for(EgressAllowlists, org_id=org_id) as db:
            if (await db.execute(stmt)).scalar_one_or_none() is None:
                await db.rollback()
                raise PreconditionFailed(
                    f"egress allowlist {allowlist.id} is no longer at version {expected_version}"
                )
            for outbox_row in outbox_rows:
                db.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await db.commit()

    async def read_credential(self, org_id: UUID, project_id: UUID) -> RepositoryCredential | None:
        stmt = select(RepositoryCredentials).where(
            RepositoryCredentials.id == project_id, RepositoryCredentials.org_id == org_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, RepositoryCredential)

    async def create_credential(self, org_id: UUID, credential: RepositoryCredential) -> bool:
        return await self._insert(RepositoryCredentials, org_id, credential)

    async def write_credential(
        self, org_id: UUID, credential: RepositoryCredential, expected_version: int
    ) -> None:
        values = {
            k: v for k, v in to_values(credential, RepositoryCredentials).items() if k != "id"
        }
        stmt = (
            update(RepositoryCredentials)
            .where(
                RepositoryCredentials.id == credential.id,
                RepositoryCredentials.org_id == org_id,
                RepositoryCredentials.version == expected_version,
            )
            .values(**values)
            .returning(RepositoryCredentials.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                raise PreconditionFailed(
                    f"repository credential {credential.id} is no longer at version "
                    f"{expected_version}"
                )
            await session.commit()

    async def read_credentials(self, org_id: UUID, limit: int) -> list[RepositoryCredential]:
        stmt = (
            select(RepositoryCredentials)
            .where(RepositoryCredentials.org_id == org_id)
            .order_by(RepositoryCredentials.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, RepositoryCredential) for row in rows]

    async def purge_credentials(self, org_id: UUID, project_ids: list[UUID]) -> int:
        if not project_ids:
            return 0
        stmt = delete(RepositoryCredentials).where(
            RepositoryCredentials.org_id == org_id, RepositoryCredentials.id.in_(project_ids)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone

    async def purge_workspace(self, org_id: UUID, session_id: UUID) -> bool:
        stmt = delete(SessionWorkspaces).where(
            SessionWorkspaces.org_id == org_id, SessionWorkspaces.id == session_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone > 0

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        purged = 0
        for table in (SessionWorkspaces, EgressAllowlists):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                purged += deleted(await session.execute(stmt))
                await session.commit()
        return purged
