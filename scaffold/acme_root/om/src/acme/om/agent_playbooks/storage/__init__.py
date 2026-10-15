"""Storage of the agent playbooks swimlane: every published version, the
agent playbooks each session invoked, and the versions pinned to kinds as their
kind manuals. Every operation takes org_id first."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_playbooks.types.agent_playbook import (
    AgentPlaybook,
    AgentPlaybookInvocation,
    AgentPlaybookPin,
)
from acme.om.outbox.types.row import OutboxRow


class AgentPlaybookStorageInterface(ABC):
    @abstractmethod
    async def create_agent_playbook(
        self, org_id: UUID, agent_playbook: AgentPlaybook, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """A version, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already, and
        `UniqueKeyTaken` when the tenant holds that version of the name
        under another id."""
        ...

    @abstractmethod
    async def read_agent_playbook(
        self, org_id: UUID, agent_playbook_id: UUID
    ) -> AgentPlaybook | None: ...

    @abstractmethod
    async def read_latest(self, org_id: UUID, name: str) -> AgentPlaybook | None:
        """The highest version of the name."""
        ...

    @abstractmethod
    async def create_invocation(
        self, org_id: UUID, invocation: AgentPlaybookInvocation
    ) -> AgentPlaybookInvocation:
        """The invocation, or the one the session holds for that version
        already, which answers instead."""
        ...

    @abstractmethod
    async def read_invocations(
        self, org_id: UUID, agent_session_id: UUID, limit: int
    ) -> list[AgentPlaybookInvocation]:
        """The session's invocations, oldest first."""
        ...

    @abstractmethod
    async def put_pin(
        self, org_id: UUID, pin: AgentPlaybookPin, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        """The pin by its id, written or rewritten, with the rows that
        announce it, in one commit. `UniqueKeyTaken` when the tenant pinned
        the kind, in the agent project or in none, under another id; another
        tenant's id is `TenantMismatch`."""
        ...

    @abstractmethod
    async def read_pin(
        self, org_id: UUID, kind: str, agent_project_id: UUID | None
    ) -> AgentPlaybookPin | None:
        """The kind's pin in the agent project, or the tenant's when `agent_project_id`
        is None: exactly that one, never the other."""
        ...

    @abstractmethod
    async def read_pins(self, org_id: UUID, limit: int) -> list[AgentPlaybookPin]:
        """The tenant's pins, by kind, the tenant's before an agent project's."""
        ...

    @abstractmethod
    async def delete_pin(
        self, org_id: UUID, pin_id: UUID, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The pin gone, with the rows that announce it, in one commit; False,
        with nothing landed, when it was gone already."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each kind of a deleted tenant past its
        retention; returns how many went."""
        ...
