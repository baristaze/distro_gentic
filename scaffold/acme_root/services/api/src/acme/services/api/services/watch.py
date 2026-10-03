"""The watch service: a live read of a session's open streams by a scoped
handle, and take control, a command by hand, and give back, in views. The
read answers to the handle alone; every other call is the person's."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.om.context import RequestContext, TenantContext
from acme.services.api.types.agent_sessions import AgentSessionView
from acme.services.api.types.watch import (
    CommandProgressView,
    CommandRequest,
    GiveBackRequest,
    HandRunView,
    LivePageView,
    LiveReadView,
)


class WatchServiceInterface(ABC):
    @abstractmethod
    async def open_live(self, ctx: TenantContext, session_id: UUID) -> LiveReadView: ...

    @abstractmethod
    async def read_live(
        self, rctx: RequestContext, handle: str, after: Sequence[str]
    ) -> LivePageView:
        """The open streams of the handle's session. Each of `after` is
        `<step_id>:<n>`, the last part read of one stream; one that is not is
        refused."""
        ...

    @abstractmethod
    async def take_control(self, ctx: TenantContext, session_id: UUID) -> AgentSessionView: ...

    @abstractmethod
    async def run_command(
        self, ctx: TenantContext, session_id: UUID, body: CommandRequest, key: UUID
    ) -> HandRunView:
        """The command under `key`, the id the idempotency record minted."""
        ...

    @abstractmethod
    async def command(
        self, ctx: TenantContext, session_id: UUID, key: UUID, after_seq: int
    ) -> CommandProgressView: ...

    @abstractmethod
    async def give_back(
        self, ctx: TenantContext, session_id: UUID, body: GiveBackRequest
    ) -> AgentSessionView: ...
