"""The agent projects swimlane: a tenant's agent projects, each bound to one repository,
and the agent project each session belongs to.

An agent project's name may change, and an agent project no session belongs to may be
removed; its repository never moves. A session started under an agent project
belongs to it from before its row is written, and a session spawned or handed over belongs to the agent project of
the session it came from. Nothing moves a session to another agent project. The
namespaces that key a policy by agent project read the session's agent project here,
and the one repository its own branch and pull request count as work
product on."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_projects.types.agent_project import AgentProject, AgentWorkspaceBase, Repository
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents.types.request import Start
from acme.om.context import TenantContext


class AgentProjectsManagerInterface(ABC):
    @abstractmethod
    async def create_agent_project(
        self, ctx: TenantContext, agent_project: AgentProject
    ) -> AgentProject:
        """An agent project of the tenant, bound to its repository, as one who
        writes the tenant's configuration may (`manage_members`). Announced.
        The provenance is the manager's. An id written already answers the
        agent project as stored; one another tenant holds is `TenantMismatch`."""
        ...

    @abstractmethod
    async def get_agent_project(self, ctx: TenantContext, agent_project_id: UUID) -> AgentProject:
        """An agent project of the tenant; one another tenant holds is `NotFound`, as
        one that never existed is."""
        ...

    @abstractmethod
    async def list_agent_projects(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> tuple[AgentProject, ...]:
        """The tenant's agent projects by id, strictly after `after`; `limit` is
        clamped."""
        ...

    @abstractmethod
    async def rename_agent_project(
        self, ctx: TenantContext, agent_project_id: UUID, name: str
    ) -> AgentProject:
        """The agent project under its new name, as one who writes the tenant's
        configuration may (`manage_members`). Announced. Its repository never
        moves. Another tenant's agent project is `NotFound`."""
        ...

    @abstractmethod
    async def set_workspace_base(
        self,
        ctx: TenantContext,
        agent_project_id: UUID,
        agent_workspace_base: AgentWorkspaceBase | None,
    ) -> AgentProject:
        """The agent project with the workspace base its sessions' workspaces start
        from, or with none, as one who writes the tenant's configuration may
        (`manage_members`). Announced. It reaches the sessions created after
        it; each session keeps the one it pinned. Another tenant's agent project
        is `NotFound`."""
        ...

    @abstractmethod
    async def remove_agent_project(
        self, ctx: TenantContext, agent_project_id: UUID
    ) -> AgentProject:
        """Removes an agent project no session belongs to, as one who writes the
        tenant's configuration may (`manage_members`), and answers it as it
        stood. Announced. One a session belongs to is `AgentProjectInUse`, and
        stays; another tenant's is `NotFound`."""
        ...

    @abstractmethod
    async def start_agent_session(
        self, ctx: TenantContext, agent_project_id: UUID, start: Start
    ) -> AgentSession:
        """Starts a root session under an agent project of the caller's tenant, as
        the agents' start does: the session belongs to the agent project before
        its row is written. Another tenant's agent project is `NotFound`, and
        nothing is written. Started again under the same agent project, the
        session is answered as the agents' start answers it; under another,
        or for a session that stands already under none, `AgentProjectFixed`."""
        ...

    @abstractmethod
    async def agent_project_of(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentProject | None:
        """The agent project the session belongs to; None for a session with no
        agent project row, never another agent project."""
        ...

    @abstractmethod
    async def work_repository(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> Repository | None:
        """The one repository the session's own branch and pull request
        count as work product on: its agent project's. None for a session with no
        agent project row, so no write of it is work product."""
        ...

    @abstractmethod
    async def purge_agent_session(self, org_id: UUID, agent_session_id: UUID) -> bool:
        """Platform-internal: the agent project row of a session the sweep has
        claimed for its purge goes before the session's row, under the purge
        login, in the tenant named; for no principal. False when none was
        left."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its sessions'
        agent project rows, then its agent projects, a batch at most a call. Any other
        tenant returns 0 and reads nothing."""
        ...
