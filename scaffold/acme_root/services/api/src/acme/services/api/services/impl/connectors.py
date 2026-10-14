from uuid import UUID

from acme.om.connectors import ConnectorsManagerInterface
from acme.om.connectors.types.connector import (
    Connector,
    ConnectorAttachment,
    ConnectorDraft,
    ConnectorReview,
)
from acme.om.context import TenantContext
from acme.services.api.services.connectors import ConnectorsServiceInterface
from acme.services.api.services.impl.built import built
from acme.services.api.types.connectors import (
    AttachmentView,
    AttachRequest,
    ConnectorReviewRequest,
    ConnectorToolView,
    ConnectorView,
    ConnectRequest,
    CredentialRequest,
    ListedToolView,
)
from acme.services.api.types.levers import FindingView


class ConnectorsServiceImpl(ConnectorsServiceInterface):
    def __init__(self, connectors: ConnectorsManagerInterface) -> None:
        self._connectors = connectors

    async def connect_server(
        self, ctx: TenantContext, body: ConnectRequest, connector_id: UUID
    ) -> ConnectorView:
        draft = built(ConnectorDraft, body.model_dump())
        connected = await self._connectors.connect_server(ctx, draft, connector_id=connector_id)
        return view_of(connected)

    async def put_credential(
        self, ctx: TenantContext, connector_id: UUID, body: CredentialRequest
    ) -> ConnectorView:
        return view_of(await self._connectors.put_credential(ctx, connector_id, body.value))

    async def list_connectors(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> list[ConnectorView]:
        return [view_of(each) for each in await self._connectors.list_connectors(ctx, after, limit)]

    async def get_connector(self, ctx: TenantContext, connector_id: UUID) -> ConnectorView:
        return view_of(await self._connectors.get_connector(ctx, connector_id))

    async def listing(self, ctx: TenantContext, connector_id: UUID) -> list[ListedToolView]:
        return [
            ListedToolView(
                name=each.definition.name,
                description=each.definition.description,
                input_schema=dict(each.definition.model_dump(mode="json")["input_schema"]),
                annotations=dict(each.definition.model_dump(mode="json")["annotations"]),
                definition_hash=each.definition_hash,
                findings=[FindingView.model_validate(f) for f in each.findings],
            )
            for each in await self._connectors.listing(ctx, connector_id)
        ]

    async def review(
        self, ctx: TenantContext, connector_id: UUID, body: ConnectorReviewRequest
    ) -> ConnectorView:
        review = built(ConnectorReview, body.model_dump())
        return view_of(await self._connectors.review(ctx, connector_id, review))

    async def attach(
        self, ctx: TenantContext, connector_id: UUID, body: AttachRequest
    ) -> ConnectorView:
        attachment = ConnectorAttachment(
            kind=body.kind, agent_project_id=body.agent_project_id, deferred=body.deferred
        )
        return view_of(await self._connectors.attach(ctx, connector_id, attachment))

    async def detach(
        self, ctx: TenantContext, connector_id: UUID, kind: str, agent_project_id: UUID | None
    ) -> ConnectorView:
        return view_of(await self._connectors.detach(ctx, connector_id, kind, agent_project_id))


def view_of(connector: Connector) -> ConnectorView:
    """A connector as the API answers it: whether its calls carry a
    credential, never the credential or the secret that holds it."""
    return ConnectorView(
        id=connector.id,
        name=connector.name,
        summary=connector.summary,
        place=connector.place,
        url=connector.url,
        credential_header=connector.credential_header,
        credential_scheme=connector.credential_scheme,
        has_credential=connector.secret is not None,
        host_server=connector.host_server,
        tools=[
            ConnectorToolView(
                name=tool.name,
                server_tool=tool.definition.name,
                description=tool.definition.description,
                input_schema=dict(tool.definition.model_dump(mode="json")["input_schema"]),
                definition_hash=tool.definition_hash,
                authorization_class=tool.authorization_class,
                effect=tool.effect,
                findings=[FindingView.model_validate(f) for f in tool.findings],
            )
            for tool in connector.tools
        ],
        review=connector.review,
        reviewed_by=connector.reviewed_by,
        attachments=[AttachmentView.model_validate(each) for each in connector.attachments],
        version=connector.version,
        created_at=connector.created_at,
        updated_at=connector.updated_at,
    )
