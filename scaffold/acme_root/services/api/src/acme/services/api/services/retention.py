"""The retention service: the tenant's policy, read, and written whole on the
version the caller read; and one session's content, erased now."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.retention import (
    RetentionRequest,
    RetentionView,
    SessionRetentionView,
)


class RetentionServiceInterface(ABC):
    @abstractmethod
    async def get_policy(self, ctx: TenantContext) -> RetentionView: ...

    @abstractmethod
    async def write_policy(
        self, ctx: TenantContext, body: RetentionRequest, version: int | None
    ) -> RetentionView:
        """The policy written over the version the caller read, or, with
        none named, as the tenant's first: one that moved, or a first when
        the tenant has declared one, is `PreconditionFailed`."""
        ...

    @abstractmethod
    async def erase_content(self, ctx: TenantContext, session_id: UUID) -> SessionRetentionView:
        """The session's content erased, its shape kept, and its snapshot as
        the erasure left it."""
        ...
