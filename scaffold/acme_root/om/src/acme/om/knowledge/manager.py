"""The knowledge swimlane: what a session should not rediscover, recalled
into it when its trigger matches, as data. An agent may suggest an entry;
only a person's review lets any session recall it, so one session cannot
plant instructions for the next."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.knowledge.types.knowledge import Knowledge


class KnowledgeManagerInterface(ABC):
    @abstractmethod
    async def suggest(
        self, ctx: TenantContext, session_id: UUID, title: str, trigger: tuple[str, ...], text: str
    ) -> Knowledge:
        """An entry an agent suggests from its session, as its call's context
        may: it waits for a person's review and is recalled by no session
        before it."""
        ...

    @abstractmethod
    async def write(
        self, ctx: TenantContext, title: str, trigger: tuple[str, ...], text: str
    ) -> Knowledge:
        """An entry a person writes in person, reviewed by them as they write
        it. An agent's call is `NotAuthorized`."""
        ...

    @abstractmethod
    async def review(self, ctx: TenantContext, entry_id: UUID, *, keep: bool) -> Knowledge:
        """A person's review of a suggestion, in person: kept, any session may
        recall it; rejected, none ever does. An agent's call is
        `NotAuthorized`; an entry reviewed already is `Conflict`."""
        ...

    @abstractmethod
    async def recall(
        self, ctx: TenantContext, session_id: UUID, about: str
    ) -> tuple[Knowledge, ...]:
        """Brings the reviewed entries whose trigger `about` matches into the
        session, each as an event it reads as data at its next model call,
        once; answers them."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its entries, a
        batch at most a call. Any other tenant returns 0."""
        ...
