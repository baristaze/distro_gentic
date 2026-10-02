from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from acme.om.exceptions import TenantMismatch
from acme.om.outbox.types.row import OutboxRow
from acme.om.projects.storage import ProjectStorageInterface
from acme.om.projects.storage.tables.projects import Projects
from acme.om.projects.storage.tables.session_projects import SessionProjects
from acme.om.projects.types.binding import SessionProject
from acme.om.projects.types.project import Project
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_values


class ProjectStoragePostgresImpl(PgStorageBase, ProjectStorageInterface):
    async def create_project(
        self, org_id: UUID, project: Project, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(Projects, org_id, project, outbox_rows)

    async def read_project(self, org_id: UUID, project_id: UUID) -> Project | None:
        stmt = select(Projects).where(Projects.org_id == org_id, Projects.id == project_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Project)

    async def bind_session(self, org_id: UUID, binding: SessionProject) -> SessionProject:
        """The insert meets the primary key when the session has a row, and
        lands nothing: the row is never updated, so the stored one stands.
        Another tenant's row is the same key, and reads as none here."""
        insert = (
            pg_insert(SessionProjects)
            .values(org_id=org_id, **to_values(binding, SessionProjects))
            .on_conflict_do_nothing(index_elements=[SessionProjects.id])
            .returning(SessionProjects.id)
        )
        stored = select(SessionProjects).where(
            SessionProjects.org_id == org_id, SessionProjects.id == binding.id
        )
        async with self._session_for(SessionProjects, org_id=org_id) as session:
            if (await session.execute(insert)).scalar_one_or_none() is not None:
                await session.commit()
                return binding
            row = (await session.execute(stored)).scalar_one_or_none()
            await session.commit()
            if row is None:
                raise TenantMismatch(f"agent session {binding.id} is not in {org_id}")
            return to_model(row, SessionProject)

    async def read_binding(self, org_id: UUID, session_id: UUID) -> SessionProject | None:
        stmt = select(SessionProjects).where(
            SessionProjects.org_id == org_id, SessionProjects.id == session_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, SessionProject)

    async def purge_session(self, org_id: UUID, session_id: UUID) -> bool:
        stmt = delete(SessionProjects).where(
            SessionProjects.org_id == org_id, SessionProjects.id == session_id
        )
        async with self._purge_session_for(SessionProjects, org_id=org_id) as session:
            purged = deleted(await session.execute(stmt))
            await session.commit()
            return purged > 0

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """The sessions' rows first, under the purge login, which alone
        deletes them and locks no row, so its batch is a plain limit under
        the tenant's purge lock; then the projects."""
        batch = select(SessionProjects.id).where(SessionProjects.org_id == org_id).limit(limit)
        bindings = delete(SessionProjects).where(
            SessionProjects.org_id == org_id, SessionProjects.id.in_(batch)
        )
        async with self._purge_session_for(SessionProjects, org_id=org_id) as session:
            gone = deleted(await session.execute(bindings))
            await session.commit()
        if gone >= limit:
            return gone
        projects = delete_batch(Projects, Projects.org_id == org_id, limit=limit - gone)
        async with self._session_for(projects, org_id=org_id) as session:
            gone += deleted(await session.execute(projects))
            await session.commit()
        return gone
