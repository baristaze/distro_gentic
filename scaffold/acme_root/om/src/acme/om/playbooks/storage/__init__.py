"""Storage of the playbooks swimlane: every published version, and the
playbooks each session invoked. Every operation takes org_id first."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.outbox.types.row import OutboxRow
from acme.om.playbooks.types.playbook import Playbook, PlaybookInvocation


class PlaybookStorageInterface(ABC):
    @abstractmethod
    async def create_playbook(
        self, org_id: UUID, playbook: Playbook, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """A version, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already, and
        `UniqueKeyTaken` when the tenant holds that version of the name
        under another id."""
        ...

    @abstractmethod
    async def read_playbook(self, org_id: UUID, playbook_id: UUID) -> Playbook | None: ...

    @abstractmethod
    async def read_latest(self, org_id: UUID, name: str) -> Playbook | None:
        """The highest version of the name."""
        ...

    @abstractmethod
    async def create_invocation(
        self, org_id: UUID, invocation: PlaybookInvocation
    ) -> PlaybookInvocation:
        """The invocation, or the one the session holds for that version
        already, which answers instead."""
        ...

    @abstractmethod
    async def read_invocations(
        self, org_id: UUID, session_id: UUID, limit: int
    ) -> list[PlaybookInvocation]:
        """The session's invocations, oldest first."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each kind of a deleted tenant past its
        retention; returns how many went."""
        ...
