from uuid import UUID

from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.agent_projects.types.agent_project import AgentProject
from acme.om.agent_projects.types.binding import SessionAgentProject
from acme.om.exceptions import TenantMismatch
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class AgentProjectStorageMemoryImpl(MemoryStorageBase, AgentProjectStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._agent_projects: MemoryTable[AgentProject] = {}
        self._bindings: MemoryTable[SessionAgentProject] = {}

    async def create_agent_project(
        self, org_id: UUID, agent_project: AgentProject, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._agent_projects, org_id, agent_project, outbox_rows)

    async def read_agent_project(self, org_id: UUID, agent_project_id: UUID) -> AgentProject | None:
        return self._get(self._agent_projects, org_id, agent_project_id)

    async def read_agent_projects(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[AgentProject]:
        rows = self._rows(self._agent_projects, org_id)
        return [p for p in rows if after is None or p.id > after][:limit]

    async def write_agent_project(
        self, org_id: UUID, agent_project: AgentProject, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if self._get(self._agent_projects, org_id, agent_project.id) is None:
                return False
            self._put(self._agent_projects, org_id, agent_project, outbox_rows)
            return True

    async def delete_agent_project(
        self, org_id: UUID, agent_project_id: UUID, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if self._get(self._agent_projects, org_id, agent_project_id) is None:
                return False
            if any(
                b.agent_project_id == agent_project_id for b in self._rows(self._bindings, org_id)
            ):
                return False
            self._land(org_id, outbox_rows)
            del self._agent_projects[agent_project_id]
            return True

    async def bind_session(self, org_id: UUID, binding: SessionAgentProject) -> SessionAgentProject:
        async with self._lock:
            if self._insert(self._bindings, org_id, binding):
                return binding
            stored = self._get(self._bindings, org_id, binding.id)
            if stored is None:
                raise TenantMismatch(f"agent session {binding.id} is not in {org_id}")
            return stored

    async def read_binding(self, org_id: UUID, session_id: UUID) -> SessionAgentProject | None:
        return self._get(self._bindings, org_id, session_id)

    async def purge_session(self, org_id: UUID, session_id: UUID) -> bool:
        async with self._lock:
            if self._get(self._bindings, org_id, session_id) is None:
                return False
            del self._bindings[session_id]
            return True

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """The sessions' rows first, so the agent projects go last."""
        async with self._lock:
            bindings = [b.id for b in self._rows(self._bindings, org_id)][:limit]
            for binding_id in bindings:
                del self._bindings[binding_id]
            agent_projects = [p.id for p in self._rows(self._agent_projects, org_id)][
                : limit - len(bindings)
            ]
            for agent_project_id in agent_projects:
                del self._agent_projects[agent_project_id]
            return len(bindings) + len(agent_projects)
