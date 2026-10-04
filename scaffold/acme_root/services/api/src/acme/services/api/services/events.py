"""The events service: the tenant's append-only stream, paged forward by
`after_seq`, or back from the head by `before_seq`."""

from abc import ABC, abstractmethod

from acme.om.context import TenantContext
from acme.services.api.types.events import EventView


class EventsServiceInterface(ABC):
    @abstractmethod
    async def get_events(
        self, ctx: TenantContext, after_seq: int, limit: int
    ) -> list[EventView]: ...

    @abstractmethod
    async def get_recent_events(
        self, ctx: TenantContext, before_seq: int | None, limit: int
    ) -> list[EventView]: ...
