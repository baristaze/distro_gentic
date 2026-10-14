"""Storage of the connectors swimlane: a tenant's connectors, and what each
session pinned of them. Every operation takes org_id first."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.connectors.types.connector import AgentSessionConnectors, Connector
from acme.om.outbox.types.row import OutboxRow


class ConnectorStorageInterface(ABC):
    @abstractmethod
    async def create_connector(
        self, org_id: UUID, connector: Connector, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The connector, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already, and
        `UniqueKeyTaken` when the tenant holds the name under another id."""
        ...

    @abstractmethod
    async def read_connector(self, org_id: UUID, connector_id: UUID) -> Connector | None: ...

    @abstractmethod
    async def read_connectors(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[Connector]:
        """The tenant's connectors by id, strictly after `after`."""
        ...

    @abstractmethod
    async def update_connector(
        self, org_id: UUID, connector: Connector, outbox_rows: tuple[OutboxRow, ...]
    ) -> None:
        """Writes the connector at its version, which is one past the version
        it was read at: `PreconditionFailed` when another write landed
        meanwhile, with nothing landed."""
        ...

    @abstractmethod
    async def create_pin(self, org_id: UUID, pin: AgentSessionConnectors) -> AgentSessionConnectors:
        """The session's pin, or the one it holds already, which answers
        instead: a session pins once."""
        ...

    @abstractmethod
    async def read_pin(self, org_id: UUID, session_id: UUID) -> AgentSessionConnectors | None: ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each kind of a deleted tenant past its
        retention; returns how many went."""
        ...
