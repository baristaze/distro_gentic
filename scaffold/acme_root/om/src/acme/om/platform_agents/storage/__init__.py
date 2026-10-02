"""Storage of the platform's agents: its validation sessions. Every
operation takes org_id first. A create lands with its outbox rows, the one
that asks for its station work among them, in one commit, and a write
after it is a compare-and-set on the version."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.outbox.types.row import OutboxRow
from acme.om.platform_agents.types.validation import ValidationSession


class PlatformAgentsStorageInterface(ABC):
    @abstractmethod
    async def read_validation(self, org_id: UUID, session_id: UUID) -> ValidationSession | None:
        """The tenant's validation session, or None."""
        ...

    @abstractmethod
    async def create_validation(
        self, org_id: UUID, session: ValidationSession, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with its outbox rows, in one commit; False, with
        nothing landed, when the id is written already."""
        ...

    @abstractmethod
    async def write_validation(
        self,
        org_id: UUID,
        session: ValidationSession,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        """The compare-and-set: lands the session and its outbox rows when the
        stored one is at `expected_version`, and raises `PreconditionFailed`
        otherwise, landing nothing."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` validation sessions of a deleted tenant past its
        retention; returns how many went."""
        ...
