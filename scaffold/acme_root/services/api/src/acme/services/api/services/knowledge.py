"""The knowledge service: a tenant's entries read by state, written and
edited by a person, and a suggestion reviewed."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.knowledge.types.knowledge import KnowledgeStatus
from acme.services.api.types.knowledge import KnowledgeRequest, KnowledgeView, ReviewRequest


class KnowledgeServiceInterface(ABC):
    @abstractmethod
    async def list_entries(
        self, ctx: TenantContext, status: KnowledgeStatus, after: UUID | None, limit: int
    ) -> list[KnowledgeView]: ...

    @abstractmethod
    async def get_entry(self, ctx: TenantContext, entry_id: UUID) -> KnowledgeView: ...

    @abstractmethod
    async def write_entry(self, ctx: TenantContext, body: KnowledgeRequest) -> KnowledgeView: ...

    @abstractmethod
    async def edit_entry(
        self, ctx: TenantContext, entry_id: UUID, body: KnowledgeRequest, version: int | None
    ) -> KnowledgeView:
        """The edit, on the version the caller read: none named is
        `ValidationFailed`, and one that moved is `PreconditionFailed`."""
        ...

    @abstractmethod
    async def review_entry(
        self, ctx: TenantContext, entry_id: UUID, body: ReviewRequest
    ) -> KnowledgeView: ...
