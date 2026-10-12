"""The connectors service: a tenant's MCP servers connected, listed,
reviewed, and attached to kinds."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.connectors import (
    AttachRequest,
    ConnectorReviewRequest,
    ConnectorView,
    ConnectRequest,
    CredentialRequest,
    ListedToolView,
)


class ConnectorsServiceInterface(ABC):
    @abstractmethod
    async def connect(
        self, ctx: TenantContext, body: ConnectRequest, connector_id: UUID
    ) -> ConnectorView: ...

    @abstractmethod
    async def put_credential(
        self, ctx: TenantContext, connector_id: UUID, body: CredentialRequest
    ) -> ConnectorView: ...

    @abstractmethod
    async def list_connectors(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[ConnectorView]: ...

    @abstractmethod
    async def get_connector(self, ctx: TenantContext, connector_id: UUID) -> ConnectorView: ...

    @abstractmethod
    async def listing(self, ctx: TenantContext, connector_id: UUID) -> list[ListedToolView]: ...

    @abstractmethod
    async def review(
        self, ctx: TenantContext, connector_id: UUID, body: ConnectorReviewRequest
    ) -> ConnectorView: ...

    @abstractmethod
    async def attach(
        self, ctx: TenantContext, connector_id: UUID, body: AttachRequest
    ) -> ConnectorView: ...

    @abstractmethod
    async def detach(
        self, ctx: TenantContext, connector_id: UUID, kind: str, project_id: UUID | None
    ) -> ConnectorView: ...
