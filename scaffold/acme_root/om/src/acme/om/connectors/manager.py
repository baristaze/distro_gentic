"""The connectors swimlane: a tenant's MCP servers, as toolsets of its
agents. A person connects a server, reviews the tools of it a session may
call, each pinned by the hash of its definition, and attaches it to a kind,
for one project or for the whole tenant. A session of that kind holds it as
a toolset, deferred unless attached otherwise, pinned as its first run
began: a later review or attachment reaches the next session, and a tool a
person withdraws or reviews again stops at its next call in every
session."""

from abc import ABC, abstractmethod
from uuid import UUID

from pydantic import SecretStr

from acme.om.connectors.types.connector import (
    Connector,
    ConnectorAttachment,
    ConnectorDraft,
    ConnectorReview,
    ListedTool,
)
from acme.om.context import TenantContext


class ConnectorsManagerInterface(ABC):
    @abstractmethod
    async def connect(
        self,
        ctx: TenantContext,
        draft: ConnectorDraft,
        *,
        credential: SecretStr | None = None,
        connector_id: UUID | None = None,
    ) -> Connector:
        """A server the tenant connects, with no tool reviewed and attached
        to no kind. A cloud server's address is one the platform's cloud
        may call, and its credential, when it takes one, is kept as the
        tenant's secret: the connector names it, never holds it. A host
        server's credential stays on its host, so it takes none here. A
        name the platform's toolsets hold is `ValidationFailed`, and one
        the tenant holds `UniqueKeyTaken`. An id written already answers
        the connector as stored, so a retry connects none."""
        ...

    @abstractmethod
    async def get_connector(self, ctx: TenantContext, connector_id: UUID) -> Connector:
        """A connector of the tenant; another tenant's is `NotFound`."""
        ...

    @abstractmethod
    async def list_connectors(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> tuple[Connector, ...]:
        """The tenant's connectors by id, strictly after `after`; `limit` is
        clamped."""
        ...

    @abstractmethod
    async def listing(self, ctx: TenantContext, connector_id: UUID) -> tuple[ListedTool, ...]:
        """What a cloud server lists now, as a person reads it before a
        review: each tool, its hash, and what the lever checks find in its
        description. A host server is listed on its host, never from here:
        `Conflict`."""
        ...

    @abstractmethod
    async def review(
        self, ctx: TenantContext, connector_id: UUID, review: ConnectorReview
    ) -> Connector:
        """A person's review, in person: the tools it names, bound at the
        definitions the server lists now (a cloud server's, listed here; a
        host server's, as the review carries them) and the hashes the
        person read, each with the lever checks' findings. It replaces the
        last review whole, and none withdraws every tool."""
        ...

    @abstractmethod
    async def attach(
        self, ctx: TenantContext, connector_id: UUID, attachment: ConnectorAttachment
    ) -> Connector:
        """The connector attached to a kind, for a project of the tenant or
        for every session: an attachment of that kind and project already
        held is replaced. A kind no catalog holds, or one whose toolsets
        share the connector's name, is `ValidationFailed`."""
        ...

    @abstractmethod
    async def detach(
        self, ctx: TenantContext, connector_id: UUID, kind: str, project_id: UUID | None
    ) -> Connector:
        """The attachment of that kind and project taken away; one the
        connector does not hold is `NotFound`. A session that pinned the
        connector keeps it."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """A batch of a deleted tenant's rows, once its retention passed."""
        ...
