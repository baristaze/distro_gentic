"""The agent fleet service: the platform's operator routes, in views. An operator
writes a tenant's fair share, reads where one of its sessions' work stands
and what one of its hosts is handed, reads a session's shape, and reads which
levers its sessions reached before they stalled; opening a session's
content takes a grant of its own in that tenant. Every call takes
`OperatorContext` and names the tenant."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.context import OperatorContext
from acme.services.api.types.agent_sessions import AgentStepPageView
from acme.services.api.types.hosts import HostStandingView
from acme.services.api.types.levers import LeverReadingView
from acme.services.api.types.placement import AgentSessionStandingView, SetShareRequest, ShareView
from acme.services.api.types.trust import ShapePageView


class AgentFleetServiceInterface(ABC):
    @abstractmethod
    async def set_share(
        self, admin: OperatorContext, org_id: UUID, body: SetShareRequest
    ) -> ShareView: ...

    @abstractmethod
    async def get_session_standing(
        self, admin: OperatorContext, org_id: UUID, agent_session_id: UUID
    ) -> AgentSessionStandingView: ...

    @abstractmethod
    async def get_host_standing(
        self, admin: OperatorContext, org_id: UUID, host_id: UUID
    ) -> HostStandingView: ...

    @abstractmethod
    async def get_session_shape(
        self,
        admin: OperatorContext,
        org_id: UUID,
        agent_session_id: UUID,
        after_seq: int,
        limit: int,
    ) -> ShapePageView: ...

    @abstractmethod
    async def get_session_content(
        self,
        admin: OperatorContext,
        org_id: UUID,
        agent_session_id: UUID,
        after_seq: int,
        limit: int,
    ) -> AgentStepPageView: ...

    @abstractmethod
    async def read_levers(
        self, admin: OperatorContext, org_id: UUID, since: datetime, until: datetime
    ) -> LeverReadingView: ...
