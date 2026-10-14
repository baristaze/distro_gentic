"""The agent knowledge service: a tenant's entries read by state, written and
edited by a person, and a suggestion reviewed."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_knowledge.types.agent_knowledge import AgentKnowledgeStatus
from acme.om.context import TenantContext
from acme.services.api.types.agent_knowledge import (
    AgentKnowledgeRequest,
    AgentKnowledgeView,
    ReviewRequest,
)


class AgentKnowledgeServiceInterface(ABC):
    @abstractmethod
    async def list_entries(
        self, ctx: TenantContext, status: AgentKnowledgeStatus, after: UUID | None, limit: int
    ) -> list[AgentKnowledgeView]: ...

    @abstractmethod
    async def get_entry(self, ctx: TenantContext, entry_id: UUID) -> AgentKnowledgeView: ...

    @abstractmethod
    async def write_entry(
        self, ctx: TenantContext, body: AgentKnowledgeRequest, entry_id: UUID
    ) -> AgentKnowledgeView: ...

    @abstractmethod
    async def edit_entry(
        self, ctx: TenantContext, entry_id: UUID, body: AgentKnowledgeRequest, version: int | None
    ) -> AgentKnowledgeView:
        """The edit, on the version the caller read: none named is
        `ValidationFailed`, and one that moved is `PreconditionFailed`."""
        ...

    @abstractmethod
    async def review_entry(
        self, ctx: TenantContext, entry_id: UUID, body: ReviewRequest
    ) -> AgentKnowledgeView: ...
