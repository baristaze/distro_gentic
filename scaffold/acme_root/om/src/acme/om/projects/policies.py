"""What a namespace that keys a policy by project reads of the projects: the
project a session belongs to, and whether a project is the tenant's.

A budget, a secret, a validation policy, and the paths it protects are set
per project, and each is read through the session's project: the answer
`ProjectsManagerInterface.project_of` gives, by id. The projects own both
answers; a root reads them from the projects' rows
(`acme.om.projects.impl.policies.SessionProjectsBoundImpl`)."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext


class SessionProjectsInterface(ABC):
    @abstractmethod
    async def project_of(self, ctx: TenantContext, session_id: UUID) -> UUID | None:
        """The id of the project the session belongs to; None for a session
        of no project, never another project."""
        ...

    @abstractmethod
    async def holds(self, ctx: TenantContext, project_id: UUID) -> bool:
        """Whether the project is one of the caller's tenant. Another
        tenant's project is not, as one that never existed is not."""
        ...
