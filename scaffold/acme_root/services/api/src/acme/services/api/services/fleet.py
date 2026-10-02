"""The fleet service: the platform's operator routes, in views. An operator
writes a tenant's fair share, reads where one of its sessions' work stands
and what one of its hosts is handed, and reads a session's shape; opening
its content takes a grant of its own in that tenant. Every call takes
`OperatorContext` and names the tenant."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import OperatorContext
from acme.services.api.types.agent_sessions import StepPageView
from acme.services.api.types.fleet import (
    HostStandingView,
    SessionStandingView,
    SetShareRequest,
    ShapePageView,
    ShareView,
)


class FleetServiceInterface(ABC):
    @abstractmethod
    async def set_share(
        self, admin: OperatorContext, org_id: UUID, body: SetShareRequest
    ) -> ShareView: ...

    @abstractmethod
    async def get_session_standing(
        self, admin: OperatorContext, org_id: UUID, session_id: UUID
    ) -> SessionStandingView: ...

    @abstractmethod
    async def get_host_standing(
        self, admin: OperatorContext, org_id: UUID, host_id: UUID
    ) -> HostStandingView: ...

    @abstractmethod
    async def get_session_shape(
        self, admin: OperatorContext, org_id: UUID, session_id: UUID, after_seq: int, limit: int
    ) -> ShapePageView: ...

    @abstractmethod
    async def get_session_content(
        self, admin: OperatorContext, org_id: UUID, session_id: UUID, after_seq: int, limit: int
    ) -> StepPageView: ...
