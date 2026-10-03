"""The tools service: the tenant's layer of tool policy, read, and written
whole on the version the caller read."""

from abc import ABC, abstractmethod

from acme.om.context import TenantContext
from acme.services.api.types.tools import ToolPolicyRequest, ToolPolicyView


class ToolsServiceInterface(ABC):
    @abstractmethod
    async def get_policy(self, ctx: TenantContext) -> ToolPolicyView: ...

    @abstractmethod
    async def write_policy(
        self, ctx: TenantContext, body: ToolPolicyRequest, version: int | None
    ) -> ToolPolicyView:
        """The layer written over the version the caller read: none named is
        `ValidationFailed`, and one that moved is `PreconditionFailed`."""
        ...
