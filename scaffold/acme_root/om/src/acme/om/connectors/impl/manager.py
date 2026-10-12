from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import Field, SecretStr

from acme.infra.secrets import SecretsInterface
from acme.integrations.mcp import McpClientInterface, McpHttp
from acme.om.agents.types.kind import AgentKindCatalog
from acme.om.base import Platform, new_id, utcnow
from acme.om.connectors.impl.addresses import Resolve, refused_now, resolve
from acme.om.connectors.manager import ConnectorsManagerInterface
from acme.om.connectors.rules import cloud_server, listed_tools, reach_with, reviewed
from acme.om.connectors.storage import ConnectorStorageInterface
from acme.om.connectors.types.connector import (
    Connector,
    ConnectorAttachment,
    ConnectorDraft,
    ConnectorPlace,
    ConnectorReview,
    ListedTool,
)
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import (
    Conflict,
    NotAuthorized,
    NotFound,
    TenantMismatch,
    UnknownAgentKind,
    ValidationFailed,
)
from acme.om.intake.rules import in_person
from acme.om.levers.types.lever import LeverReach
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, versioned_row
from acme.om.projects.policies import SessionProjectsInterface
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tools.mcp import LIST_TIMEOUT, definition_of
from acme.om.tools.types.mcp import McpToolDefinition

CREATED = "connectors.connector.created"
UPDATED = "connectors.connector.updated"  # a review, an attachment, or a detachment


class ConnectorsOptions(Platform):
    page: int = Field(default=200, gt=0)
    purge_batch: int = Field(default=1000, gt=0)
    # A cloud connector's address may be this host or a private network:
    # true on a local stack alone, whose servers run beside it.
    private_addresses: bool = False


def connector_secret(connector_id: UUID) -> str:
    """The name the tenant's secret store keeps a cloud connector's credential
    under: the connector's own, so one connector never reads another's."""
    return f"connector-{connector_id.hex}"


class ConnectorsManagerImpl(ConnectorsManagerInterface):
    """`kinds` is every kind a session may start on, whose toolsets and tools
    a connector's names never take; `reach` is what the lever checks read
    a description against. `resolve` answers the addresses a name stands
    for, which a cloud address is held to at each exchange."""

    def __init__(
        self,
        storage: ConnectorStorageInterface,
        client: McpClientInterface,
        secrets: SecretsInterface,
        kinds: AgentKindCatalog,
        projects: SessionProjectsInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: ConnectorsOptions,
        reach: LeverReach,
        *,
        resolver: Resolve = resolve,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._client = client
        self._secrets = secrets
        self._kinds = kinds
        self._projects = projects
        self._tenancy = tenancy
        self._relay = relay
        self._options = options
        self._reach = reach
        self._resolve = resolver
        self._clock = clock
        self._toolsets = frozenset(
            toolset.name for kind in kinds.kinds for toolset in (*kind.toolsets, *kind.deferred)
        )
        self._tools = frozenset(tool for kind in kinds.kinds for tool in kind.tools)

    async def connect(
        self, ctx: TenantContext, draft: ConnectorDraft, *, connector_id: UUID | None = None
    ) -> Connector:
        ctx.require(Permission.MANAGE_MEMBERS)
        if draft.name in self._toolsets:
            raise ValidationFailed(f"{draft.name} is a toolset a kind names")
        if draft.url is not None:
            refusal = await refused_now(
                draft.url, private=self._options.private_addresses, resolver=self._resolve
            )
            if refusal is not None:
                raise ValidationFailed(refusal)
        now = self._clock()
        connector = Connector(
            id=connector_id or new_id(),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            name=draft.name,
            summary=draft.summary,
            place=draft.place,
            url=draft.url,
            credential_header=draft.credential_header,
            credential_scheme=draft.credential_scheme,
            host_server=draft.host_server,
        )
        rows = (versioned_row(ctx, CREATED, connector.id, connector.version),)
        if not await self._storage.create_connector(ctx.org_id, connector, rows):
            stored = await self._storage.read_connector(ctx.org_id, connector.id)
            if stored is None:
                raise TenantMismatch(f"connector {connector.id} is not in {ctx.org_id}")
            return stored
        await self._relay_all(ctx, rows)
        return connector

    async def put_credential(
        self, ctx: TenantContext, connector_id: UUID, credential: SecretStr
    ) -> Connector:
        ctx.require(Permission.MANAGE_MEMBERS)
        connector = await self._connector(ctx, connector_id)
        if connector.url is None:
            raise ValidationFailed(f"{connector.name}'s credential stays on its host")
        if not McpHttp(url=connector.url).private:
            raise ValidationFailed("a credential goes over https, or to this host")
        secret = connector_secret(connector.id)
        await self._secrets.put(
            ctx.org_id, secret, credential.get_secret_value(), deadline=ctx.deadline
        )
        if connector.secret == secret:
            return connector
        return await self._update(ctx, self._next(ctx, connector, secret=secret))

    async def get_connector(self, ctx: TenantContext, connector_id: UUID) -> Connector:
        ctx.require(Permission.READ)
        return await self._connector(ctx, connector_id)

    async def list_connectors(
        self, ctx: TenantContext, after: UUID | None, limit: int
    ) -> tuple[Connector, ...]:
        ctx.require(Permission.READ)
        bounded = max(1, min(limit, self._options.page))
        return tuple(await self._storage.read_connectors(ctx.org_id, after, bounded))

    async def listing(self, ctx: TenantContext, connector_id: UUID) -> tuple[ListedTool, ...]:
        ctx.require(Permission.MANAGE_MEMBERS)
        connector = await self._connector(ctx, connector_id)
        if connector.place is ConnectorPlace.HOST:
            raise Conflict(
                f"{connector.name} runs on the tenant's host, which lists its tools; "
                "the platform never reaches into the wall"
            )
        definitions = await self._list(ctx, connector)
        return listed_tools(definitions, reach_with(self._reach, definitions, connector.name))

    async def review(
        self, ctx: TenantContext, connector_id: UUID, review: ConnectorReview
    ) -> Connector:
        ctx.require(Permission.MANAGE_MEMBERS)
        if not in_person(ctx):
            raise NotAuthorized("a person reviews a connector's tools, in person")
        connector = await self._connector(ctx, connector_id)
        match connector.place:
            case ConnectorPlace.CLOUD if review.definitions is not None:
                raise ValidationFailed(
                    f"{connector.name}'s tools are listed from its server, never sent"
                )
            case ConnectorPlace.CLOUD:
                listing = await self._list(ctx, connector) if review.tools else ()
            case ConnectorPlace.HOST:
                if review.tools and review.definitions is None:
                    raise ValidationFailed(
                        f"{connector.name} runs on the tenant's host: send the definitions "
                        "its host lists"
                    )
                listing = review.definitions or ()
        tools = reviewed(connector, listing, review, self._reach, self._tools)
        updated = self._next(
            ctx,
            connector,
            tools=tools,
            review=connector.review + 1,
            reviewed_by=ctx.user_id,
        )
        return await self._update(ctx, updated)

    async def attach(
        self, ctx: TenantContext, connector_id: UUID, attachment: ConnectorAttachment
    ) -> Connector:
        ctx.require(Permission.MANAGE_MEMBERS)
        connector = await self._connector(ctx, connector_id)
        try:
            self._kinds.latest(attachment.kind)
        except UnknownAgentKind:
            raise ValidationFailed(f"no kind {attachment.kind} to attach to") from None
        for kind in self._kinds.kinds:
            names = {toolset.name for toolset in (*kind.toolsets, *kind.deferred)}
            if kind.name == attachment.kind and connector.name in names:
                raise ValidationFailed(
                    f"{attachment.kind} names a toolset {connector.name} at version {kind.version}"
                )
        if attachment.project_id is not None and not await self._projects.holds(
            ctx, attachment.project_id
        ):
            raise NotFound(f"project {attachment.project_id} not found")
        kept = tuple(
            each
            for each in connector.attachments
            if (each.kind, each.project_id) != (attachment.kind, attachment.project_id)
        )
        updated = self._next(ctx, connector, attachments=(*kept, attachment))
        return await self._update(ctx, updated)

    async def detach(
        self, ctx: TenantContext, connector_id: UUID, kind: str, project_id: UUID | None
    ) -> Connector:
        ctx.require(Permission.MANAGE_MEMBERS)
        connector = await self._connector(ctx, connector_id)
        kept = tuple(
            each
            for each in connector.attachments
            if (each.kind, each.project_id) != (kind, project_id)
        )
        if len(kept) == len(connector.attachments):
            raise NotFound(f"{connector.name} is not attached to {kind} there")
        return await self._update(ctx, self._next(ctx, connector, attachments=kept))

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        # Each credential goes from the store before the row that names it.
        after: UUID | None = None
        while page := await self._storage.read_connectors(ctx.org_id, after, self._options.page):
            for connector in page:
                if connector.secret is not None:
                    await self._secrets.delete(ctx.org_id, connector.secret, deadline=ctx.deadline)
            after = page[-1].id
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    async def _list(self, ctx: TenantContext, connector: Connector) -> list[McpToolDefinition]:
        """What a cloud server lists now, called from here under the tenant's
        credential, its address held to the public internet first."""
        refusal = await refused_now(
            connector.url or "", private=self._options.private_addresses, resolver=self._resolve
        )
        if refusal is not None:
            raise ValidationFailed(refusal)
        credential = (
            None
            if connector.secret is None
            else SecretStr(
                await self._secrets.get(ctx.org_id, connector.secret, deadline=ctx.deadline)
            )
        )
        deadline = min(filter(None, (ctx.deadline, self._clock() + LIST_TIMEOUT)))
        listed = await self._client.list_tools(
            cloud_server(connector), credential, deadline=deadline
        )
        return [definition_of(tool) for tool in listed]

    def _next(self, ctx: TenantContext, connector: Connector, **update: object) -> Connector:
        return Connector.model_validate(
            {
                **dict(connector),
                **update,
                "updated_at": self._clock(),
                "updated_by": ctx.user_id,
                "version": connector.version + 1,
            }
        )

    async def _update(self, ctx: TenantContext, connector: Connector) -> Connector:
        rows = (versioned_row(ctx, UPDATED, connector.id, connector.version),)
        await self._storage.update_connector(ctx.org_id, connector, rows)
        await self._relay_all(ctx, rows)
        return connector

    async def _connector(self, ctx: TenantContext, connector_id: UUID) -> Connector:
        connector = await self._storage.read_connector(ctx.org_id, connector_id)
        if connector is None:
            raise NotFound(f"connector {connector_id} not found")
        return connector

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        await self._relay.relay_all(ctx.org_id, rows)
