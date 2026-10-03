"""The knowledge swimlane: what a session should not rediscover, recalled
into it when its trigger matches, as data, and searched and read by its
agent on demand. An agent may suggest an entry; only a person's review lets
any session recall or read it, so one session cannot plant instructions
for the next. A session reaches its tenant's entries of its own project and
of no project, never another project's or another tenant's."""

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
        may, for the session's project, or for the whole tenant when the
        session has none: it waits for a person's review and is recalled or
        read by no session before it."""
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
        """Brings the reviewed entries the session reaches whose trigger
        `about` matches into the session, each as an event it reads as data
        at its next model call, once; answers them."""
        ...

    @abstractmethod
    async def search(
        self, ctx: TenantContext, session_id: UUID, query: str, limit: int
    ) -> tuple[Knowledge, ...]:
        """The reviewed entries the session reaches that share the most of
        the query's words, best first, at most `limit`."""
        ...

    @abstractmethod
    async def read(self, ctx: TenantContext, session_id: UUID, slug: str) -> Knowledge:
        """The reviewed entry of `slug` the session reaches. One waiting for
        its review, rejected, of another project, or of another tenant is
        `NotFound`, as one that never existed is."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its entries, a
        batch at most a call. Any other tenant returns 0."""
        ...
