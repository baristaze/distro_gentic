"""Storage of the agent knowledge swimlane: the tenant's entries, suggested,
reviewed, or rejected, and the versions each session recalled. Every
operation takes org_id first."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_knowledge.types.agent_knowledge import (
    AgentKnowledge,
    AgentKnowledgeRecall,
    AgentKnowledgeStatus,
)
from acme.om.outbox.types.row import OutboxRow


class AgentKnowledgeStorageInterface(ABC):
    @abstractmethod
    async def create_entry(
        self, org_id: UUID, entry: AgentKnowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already."""
        ...

    @abstractmethod
    async def read_entry(self, org_id: UUID, entry_id: UUID) -> AgentKnowledge | None: ...

    @abstractmethod
    async def read_entries(
        self, org_id: UUID, status: AgentKnowledgeStatus, after: UUID | None, limit: int
    ) -> list[AgentKnowledge]:
        """The tenant's entries in a status, by id, strictly after `after`."""
        ...

    @abstractmethod
    async def read_reachable(
        self, org_id: UUID, project_id: UUID | None, after: UUID | None, limit: int
    ) -> list[AgentKnowledge]:
        """The tenant's reviewed entries a session of `project_id` reaches
        (None for one of no project): the project's own and those of no
        project, never another project's, by id, strictly after `after`."""
        ...

    @abstractmethod
    async def read_by_slug(
        self, org_id: UUID, project_id: UUID | None, slug: str
    ) -> AgentKnowledge | None:
        """The reviewed entry of `slug` a session of `project_id` reaches, as
        `read_reachable` bounds it; None for any other."""
        ...

    @abstractmethod
    async def update_entry(
        self, org_id: UUID, entry: AgentKnowledge, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        """The entry at its new version, conditioned on the one before it
        (`PreconditionFailed` when another write landed first)."""
        ...

    @abstractmethod
    async def create_recalls(self, org_id: UUID, recalls: tuple[AgentKnowledgeRecall, ...]) -> None:
        """The recalls of one session, in one commit; one of an entry the
        session recalled already lands nothing."""
        ...

    @abstractmethod
    async def read_recalls(
        self, org_id: UUID, session_id: UUID, limit: int
    ) -> list[AgentKnowledgeRecall]:
        """The entries a session recalled, oldest first, at most `limit`."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` entries, and as many recalls, of a deleted tenant
        past its retention; returns how many went."""
        ...
