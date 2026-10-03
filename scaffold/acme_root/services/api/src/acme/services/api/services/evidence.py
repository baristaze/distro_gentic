"""The evidence service: what a session ran to show its work, and what it
delivered, in views. Every read names the session, which is read in the
tenant first, so another tenant's names nothing."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.evidence import DeliveryView, ExecutionPageView, ValidationView


class EvidenceServiceInterface(ABC):
    @abstractmethod
    async def get_executions(
        self, ctx: TenantContext, session_id: UUID, cursor: str | None, limit: int
    ) -> ExecutionPageView:
        """One page of the session's runs, oldest first."""
        ...

    @abstractmethod
    async def get_validations(
        self, ctx: TenantContext, session_id: UUID, limit: int
    ) -> list[ValidationView]:
        """The session's validations and baselines, oldest first."""
        ...

    @abstractmethod
    async def get_delivery(self, ctx: TenantContext, session_id: UUID) -> DeliveryView: ...
