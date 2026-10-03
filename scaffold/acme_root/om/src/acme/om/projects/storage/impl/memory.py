from uuid import UUID

from acme.om.exceptions import TenantMismatch
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.projects.storage import ProjectStorageInterface
from acme.om.projects.types.binding import SessionProject
from acme.om.projects.types.project import Project
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class ProjectStorageMemoryImpl(MemoryStorageBase, ProjectStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._projects: MemoryTable[Project] = {}
        self._bindings: MemoryTable[SessionProject] = {}

    async def create_project(
        self, org_id: UUID, project: Project, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._projects, org_id, project, outbox_rows)

    async def read_project(self, org_id: UUID, project_id: UUID) -> Project | None:
        return self._get(self._projects, org_id, project_id)

    async def read_projects(self, org_id: UUID, after: UUID | None, limit: int) -> list[Project]:
        rows = self._rows(self._projects, org_id)
        return [p for p in rows if after is None or p.id > after][:limit]

    async def write_project(
        self, org_id: UUID, project: Project, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if self._get(self._projects, org_id, project.id) is None:
                return False
            self._put(self._projects, org_id, project, outbox_rows)
            return True

    async def delete_project(
        self, org_id: UUID, project_id: UUID, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if self._get(self._projects, org_id, project_id) is None:
                return False
            if any(b.project_id == project_id for b in self._rows(self._bindings, org_id)):
                return False
            self._land(org_id, outbox_rows)
            del self._projects[project_id]
            return True

    async def bind_session(self, org_id: UUID, binding: SessionProject) -> SessionProject:
        async with self._lock:
            if self._insert(self._bindings, org_id, binding):
                return binding
            stored = self._get(self._bindings, org_id, binding.id)
            if stored is None:
                raise TenantMismatch(f"agent session {binding.id} is not in {org_id}")
            return stored

    async def read_binding(self, org_id: UUID, session_id: UUID) -> SessionProject | None:
        return self._get(self._bindings, org_id, session_id)

    async def purge_session(self, org_id: UUID, session_id: UUID) -> bool:
        async with self._lock:
            if self._get(self._bindings, org_id, session_id) is None:
                return False
            del self._bindings[session_id]
            return True

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """The sessions' rows first, so the projects go last."""
        async with self._lock:
            bindings = [b.id for b in self._rows(self._bindings, org_id)][:limit]
            for binding_id in bindings:
                del self._bindings[binding_id]
            projects = [p.id for p in self._rows(self._projects, org_id)][: limit - len(bindings)]
            for project_id in projects:
                del self._projects[project_id]
            return len(bindings) + len(projects)
