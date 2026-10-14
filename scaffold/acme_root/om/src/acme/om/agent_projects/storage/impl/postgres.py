from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.agent_projects.storage.tables.agent_projects import AgentProjects
from acme.om.agent_projects.storage.tables.agent_session_projects import AgentSessionProjects
from acme.om.agent_projects.types.agent_project import AgentProject
from acme.om.agent_projects.types.binding import SessionAgentProject
from acme.om.exceptions import TenantMismatch
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values


class AgentProjectStoragePostgresImpl(PgStorageBase, AgentProjectStorageInterface):
    async def create_agent_project(
        self, org_id: UUID, agent_project: AgentProject, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(AgentProjects, org_id, agent_project, outbox_rows)

    async def read_agent_project(self, org_id: UUID, agent_project_id: UUID) -> AgentProject | None:
        stmt = select(AgentProjects).where(
            AgentProjects.org_id == org_id, AgentProjects.id == agent_project_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentProject)

    async def read_agent_projects(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[AgentProject]:
        stmt = select(AgentProjects).where(AgentProjects.org_id == org_id)
        if after is not None:
            stmt = stmt.where(AgentProjects.id > after)
        stmt = stmt.order_by(AgentProjects.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, AgentProject) for row in rows]

    async def write_agent_project(
        self, org_id: UUID, agent_project: AgentProject, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        values = {k: v for k, v in to_values(agent_project, AgentProjects).items() if k != "id"}
        stmt = (
            update(AgentProjects)
            .where(AgentProjects.org_id == org_id, AgentProjects.id == agent_project.id)
            .values(**values)
            .returning(AgentProjects.id)
        )
        return await self._landed(stmt, org_id, outbox_rows)

    async def delete_agent_project(
        self, org_id: UUID, agent_project_id: UUID, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The session rows are asked in the delete's own WHERE, so a session
        row that stands when it runs keeps its agent project."""
        in_use = exists().where(
            AgentSessionProjects.org_id == org_id,
            AgentSessionProjects.agent_project_id == agent_project_id,
        )
        stmt = (
            delete(AgentProjects)
            .where(AgentProjects.org_id == org_id, AgentProjects.id == agent_project_id, ~in_use)
            .returning(AgentProjects.id)
        )
        return await self._landed(stmt, org_id, outbox_rows)

    async def _landed(self, stmt: Any, org_id: UUID, outbox_rows: tuple[OutboxRow, ...]) -> bool:
        """A statement that returns the agent project's id when it touched it, and
        the rows that announce it, in one commit; nothing lands when it
        touched none."""
        async with self._session_for(AgentProjects, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                return False
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return True

    async def bind_session(self, org_id: UUID, binding: SessionAgentProject) -> SessionAgentProject:
        """The insert meets the primary key when the session has a row, and
        lands nothing: the row is never updated, so the stored one stands.
        Another tenant's row is the same key, and reads as none here."""
        insert = (
            pg_insert(AgentSessionProjects)
            .values(org_id=org_id, **to_values(binding, AgentSessionProjects))
            .on_conflict_do_nothing(index_elements=[AgentSessionProjects.id])
            .returning(AgentSessionProjects.id)
        )
        stored = select(AgentSessionProjects).where(
            AgentSessionProjects.org_id == org_id, AgentSessionProjects.id == binding.id
        )
        async with self._session_for(AgentSessionProjects, org_id=org_id) as session:
            if (await session.execute(insert)).scalar_one_or_none() is not None:
                await session.commit()
                return binding
            row = (await session.execute(stored)).scalar_one_or_none()
            await session.commit()
            if row is None:
                raise TenantMismatch(f"agent session {binding.id} is not in {org_id}")
            return to_model(row, SessionAgentProject)

    async def read_binding(self, org_id: UUID, session_id: UUID) -> SessionAgentProject | None:
        stmt = select(AgentSessionProjects).where(
            AgentSessionProjects.org_id == org_id, AgentSessionProjects.id == session_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, SessionAgentProject)

    async def purge_session(self, org_id: UUID, session_id: UUID) -> bool:
        stmt = delete(AgentSessionProjects).where(
            AgentSessionProjects.org_id == org_id, AgentSessionProjects.id == session_id
        )
        async with self._purge_session_for(AgentSessionProjects, org_id=org_id) as session:
            purged = deleted(await session.execute(stmt))
            await session.commit()
            return purged > 0

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """The sessions' rows first, under the purge login, which alone
        deletes them and locks no row, so its batch is a plain limit under
        the tenant's purge lock; then the agent projects."""
        batch = (
            select(AgentSessionProjects.id)
            .where(AgentSessionProjects.org_id == org_id)
            .limit(limit)
        )
        bindings = delete(AgentSessionProjects).where(
            AgentSessionProjects.org_id == org_id, AgentSessionProjects.id.in_(batch)
        )
        async with self._purge_session_for(AgentSessionProjects, org_id=org_id) as session:
            gone = deleted(await session.execute(bindings))
            await session.commit()
        if gone >= limit:
            return gone
        agent_projects = delete_batch(
            AgentProjects, AgentProjects.org_id == org_id, limit=limit - gone
        )
        async with self._session_for(agent_projects, org_id=org_id) as session:
            gone += deleted(await session.execute(agent_projects))
            await session.commit()
        return gone
