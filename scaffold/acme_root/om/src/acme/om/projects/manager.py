"""The projects swimlane: a tenant's projects, each bound to one repository,
and the project each session belongs to.

A project's name may change, and a project no session belongs to may be
removed; its repository never moves. A session started under a project
belongs to it from before its row is written, and a session spawned or handed over belongs to the project of
the session it came from. Nothing moves a session to another project. The
namespaces that key a policy by project read the session's project here,
and the one repository its own branch and pull request count as work
product on."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents.types.request import Start
from acme.om.context import TenantContext
from acme.om.projects.types.project import Project, Repository


class ProjectsManagerInterface(ABC):
    @abstractmethod
    async def create_project(self, ctx: TenantContext, project: Project) -> Project:
        """A project of the tenant, bound to its repository, as one who
        writes the tenant's configuration may (`manage_members`). Announced.
        The provenance is the manager's. An id written already answers the
        project as stored; one another tenant holds is `TenantMismatch`."""
        ...

    @abstractmethod
    async def get_project(self, ctx: TenantContext, project_id: UUID) -> Project:
        """A project of the tenant; one another tenant holds is `NotFound`, as
        one that never existed is."""
        ...

    @abstractmethod
    async def list_projects(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> tuple[Project, ...]:
        """The tenant's projects by id, strictly after `after`; `limit` is
        clamped."""
        ...

    @abstractmethod
    async def rename_project(self, ctx: TenantContext, project_id: UUID, name: str) -> Project:
        """The project under its new name, as one who writes the tenant's
        configuration may (`manage_members`). Announced. Its repository never
        moves. Another tenant's project is `NotFound`."""
        ...

    @abstractmethod
    async def remove_project(self, ctx: TenantContext, project_id: UUID) -> Project:
        """Removes a project no session belongs to, as one who writes the
        tenant's configuration may (`manage_members`), and answers it as it
        stood. Announced. One a session belongs to is `ProjectInUse`, and
        stays; another tenant's is `NotFound`."""
        ...

    @abstractmethod
    async def start_session(
        self, ctx: TenantContext, project_id: UUID, start: Start
    ) -> AgentSession:
        """Starts a root session under a project of the caller's tenant, as
        the agents' start does: the session belongs to the project before
        its row is written. Another tenant's project is `NotFound`, and
        nothing is written. Started again under the same project, the
        session is answered as the agents' start answers it; under another,
        or for a session that stands already under none, `ProjectFixed`."""
        ...

    @abstractmethod
    async def project_of(self, ctx: TenantContext, session_id: UUID) -> Project | None:
        """The project the session belongs to; None for a session with no
        project row, never another project."""
        ...

    @abstractmethod
    async def work_repository(self, ctx: TenantContext, session_id: UUID) -> Repository | None:
        """The one repository the session's own branch and pull request
        count as work product on: its project's. None for a session with no
        project row, so no write of it is work product."""
        ...

    @abstractmethod
    async def purge_session(self, org_id: UUID, session_id: UUID) -> bool:
        """Platform-internal: the project row of a session the sweep has
        claimed for its purge goes before the session's row, under the purge
        login, in the tenant named; for no principal. False when none was
        left."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its sessions'
        project rows, then its projects, a batch at most a call. Any other
        tenant returns 0 and reads nothing."""
        ...
