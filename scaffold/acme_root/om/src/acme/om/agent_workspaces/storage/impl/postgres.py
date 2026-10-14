from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update

from acme.om.agent_workspaces.storage import AgentWorkspaceStorageInterface
from acme.om.agent_workspaces.storage.tables.agent_session_workspaces import AgentSessionWorkspaces
from acme.om.agent_workspaces.storage.tables.agent_workspace_snapshots import (
    AgentWorkspaceSnapshots,
)
from acme.om.agent_workspaces.storage.tables.egress_allowlists import EgressAllowlists
from acme.om.agent_workspaces.storage.tables.repository_credentials import RepositoryCredentials
from acme.om.agent_workspaces.types.credential import RepositoryCredential
from acme.om.agent_workspaces.types.egress import EgressAllowlist
from acme.om.agent_workspaces.types.snapshot import KeptSnapshot
from acme.om.agent_workspaces.types.workspace import AgentSessionWorkspace
from acme.om.exceptions import PreconditionFailed
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values


class AgentWorkspaceStoragePostgresImpl(PgStorageBase, AgentWorkspaceStorageInterface):
    async def read_workspace(self, org_id: UUID, session_id: UUID) -> AgentSessionWorkspace | None:
        stmt = select(AgentSessionWorkspaces).where(
            AgentSessionWorkspaces.id == session_id, AgentSessionWorkspaces.org_id == org_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentSessionWorkspace)

    async def create_workspace(self, org_id: UUID, workspace: AgentSessionWorkspace) -> bool:
        return await self._insert(AgentSessionWorkspaces, org_id, workspace)

    async def write_workspace(
        self, org_id: UUID, workspace: AgentSessionWorkspace, expected_version: int
    ) -> None:
        values = {
            k: v for k, v in to_values(workspace, AgentSessionWorkspaces).items() if k != "id"
        }
        # The version is in the WHERE, so two writers from one snapshot
        # cannot both land.
        stmt = (
            update(AgentSessionWorkspaces)
            .where(
                AgentSessionWorkspaces.id == workspace.id,
                AgentSessionWorkspaces.org_id == org_id,
                AgentSessionWorkspaces.version == expected_version,
            )
            .values(**values)
            .returning(AgentSessionWorkspaces.id)
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

    async def create_snapshot(self, org_id: UUID, snapshot: KeptSnapshot) -> bool:
        return await self._insert(AgentWorkspaceSnapshots, org_id, snapshot)

    async def read_snapshot(self, org_id: UUID, snapshot_id: UUID) -> KeptSnapshot | None:
        stmt = select(AgentWorkspaceSnapshots).where(
            AgentWorkspaceSnapshots.org_id == org_id, AgentWorkspaceSnapshots.id == snapshot_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, KeptSnapshot)

    async def read_snapshots(
        self, org_id: UUID, session_id: UUID, limit: int
    ) -> list[KeptSnapshot]:
        stmt = (
            select(AgentWorkspaceSnapshots)
            .where(
                AgentWorkspaceSnapshots.org_id == org_id,
                AgentWorkspaceSnapshots.session_id == session_id,
            )
            .order_by(AgentWorkspaceSnapshots.created_at, AgentWorkspaceSnapshots.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, KeptSnapshot) for row in rows]

    async def purge_snapshots(self, org_id: UUID, session_id: UUID) -> int:
        stmt = delete(AgentWorkspaceSnapshots).where(
            AgentWorkspaceSnapshots.org_id == org_id,
            AgentWorkspaceSnapshots.session_id == session_id,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone

    async def purge_workspace(self, org_id: UUID, session_id: UUID) -> bool:
        stmt = delete(AgentSessionWorkspaces).where(
            AgentSessionWorkspaces.org_id == org_id, AgentSessionWorkspaces.id == session_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone > 0

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        purged = 0
        for table in (AgentSessionWorkspaces, EgressAllowlists, AgentWorkspaceSnapshots):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                purged += deleted(await session.execute(stmt))
                await session.commit()
        return purged
