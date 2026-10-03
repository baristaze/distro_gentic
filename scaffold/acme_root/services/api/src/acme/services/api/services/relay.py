"""The relay service: what a host's calls do with the `exec` items it
holds, and its control stream, in views."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from uuid import UUID

from acme.om.context import RequestContext
from acme.om.hosts.types.host import HostIdentity
from acme.services.api.types.relay import (
    ControlView,
    ExecDetailView,
    ExecLeaseView,
    PartRequest,
    PreparedView,
    PrepareRequest,
    ResultRequest,
)


class RelayServiceInterface(ABC):
    @abstractmethod
    async def detail(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID
    ) -> ExecDetailView: ...

    @abstractmethod
    async def push_part(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, body: PartRequest
    ) -> None: ...

    @abstractmethod
    async def push_result(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, body: ResultRequest
    ) -> None: ...

    @abstractmethod
    async def prepared(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, body: PrepareRequest
    ) -> PreparedView: ...

    @abstractmethod
    async def released(self, rctx: RequestContext, host: HostIdentity, item_id: UUID) -> None: ...

    @abstractmethod
    async def extend(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID
    ) -> ExecLeaseView: ...

    @abstractmethod
    def control(
        self, rctx: RequestContext, host: HostIdentity, after: UUID | None
    ) -> AsyncIterator[ControlView]:
        """The host's control stream, from inside its wall: a wake when work
        reaches its lanes, each control message for an item it holds as it
        is made, and a ping while nothing happens. It ends after its span,
        or when the credential it opened with ends; the host opens the next
        with the credential it holds then, so a rotated or a revoked one is
        met at that open, never inside a stream."""
        ...
