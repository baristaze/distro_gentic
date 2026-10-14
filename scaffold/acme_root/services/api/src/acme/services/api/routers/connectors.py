"""A tenant's connectors: its MCP servers, as toolsets of its agents. A
person who manages the tenant connects a server, reads what it lists, and
reviews the tools a session may call, in person; then attaches it to a
kind, for one agent project or the whole tenant. A cloud server's credential is
written apart, with a PUT, and never comes back."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.resolve import ConnectorsService
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.connectors import (
    AttachRequest,
    ConnectorReviewRequest,
    ConnectorView,
    ConnectRequest,
    CredentialRequest,
    ListedToolView,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("", response_model=list[ConnectorView])
async def list_connectors(
    ctx: Ctx,
    connectors: ConnectorsService,
    after: UUID | None = None,
    limit: int = LIMIT_DEFAULT,
) -> list[ConnectorView]:
    """The tenant's connectors by id, after the id `after` names."""
    return await connectors.list_connectors(ctx, after, limit)


@router.post("", response_model=ConnectorView, status_code=201)
async def connect_server(
    ctx: Ctx, connectors: ConnectorsService, body: ConnectRequest, idem: Idem
) -> Response:
    """A server connected, with no credential and no tool reviewed. Requires
    managing the org. A cloud address that is this host or a private
    network is refused."""
    return await idem.run(
        201, lambda attempt: connectors.connect_server(ctx, body, attempt.target_id)
    )


@router.put("/{connector_id}/credential", response_model=ConnectorView)
async def put_credential(
    ctx: Ctx, connectors: ConnectorsService, connector_id: UUID, body: CredentialRequest
) -> ConnectorView:
    """A cloud server's credential, written over the last one; a session's
    next call carries it. Requires managing the org. A host's server keeps
    its credential on its host: 422."""
    return await connectors.put_credential(ctx, connector_id, body)


@router.get("/{connector_id}", response_model=ConnectorView)
async def get_connector(
    ctx: Ctx, connectors: ConnectorsService, connector_id: UUID
) -> ConnectorView:
    return await connectors.get_connector(ctx, connector_id)


@router.get("/{connector_id}/listing", response_model=list[ListedToolView])
async def listing(
    ctx: Ctx, connectors: ConnectorsService, connector_id: UUID
) -> list[ListedToolView]:
    """What a cloud server lists now, each tool with the hash a review names
    and the lever checks' findings. A host's server is listed on its host:
    409."""
    return await connectors.listing(ctx, connector_id)


@router.post("/{connector_id}/review", response_model=ConnectorView)
async def review(
    ctx: Ctx, connectors: ConnectorsService, connector_id: UUID, body: ConnectorReviewRequest
) -> ConnectorView:
    """The tools a session may call, each at the hash the person read; in
    person. It replaces the last review, and none withdraws every tool."""
    return await connectors.review(ctx, connector_id, body)


@router.post("/{connector_id}/attachments", response_model=ConnectorView)
async def attach(
    ctx: Ctx, connectors: ConnectorsService, connector_id: UUID, body: AttachRequest
) -> ConnectorView:
    """The connector attached to a kind: an attachment of that kind and
    agent project already held is replaced."""
    return await connectors.attach(ctx, connector_id, body)


@router.delete("/{connector_id}/attachments", response_model=ConnectorView)
async def detach(
    ctx: Ctx,
    connectors: ConnectorsService,
    connector_id: UUID,
    kind: str,
    agent_project_id: UUID | None = None,
) -> ConnectorView:
    """The attachment of `kind` and `agent_project_id` taken away. A session that
    pinned the connector keeps it."""
    return await connectors.detach(ctx, connector_id, kind, agent_project_id)
