"""The change events service: the tenant's append-only stream, paged forward
by `after_seq`, or back from the head by `before_seq`."""

from abc import ABC, abstractmethod

from acme.om.context import TenantContext
from acme.services.api.types.change_events import ChangeEventView


class ChangeEventsServiceInterface(ABC):
    @abstractmethod
    async def get_change_events(
        self, ctx: TenantContext, after_seq: int, limit: int
    ) -> list[ChangeEventView]: ...

    @abstractmethod
    async def get_recent_change_events(
        self, ctx: TenantContext, before_seq: int | None, limit: int
    ) -> list[ChangeEventView]: ...
