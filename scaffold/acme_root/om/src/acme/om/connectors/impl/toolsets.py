"""A session's connectors as toolsets: pinned as its first run begins, and
built into tools over the engine's MCP binding at every run.

A cloud connector's tool is called from the platform's cloud through the
MCP client, its credential resolved at the call and audited by name. A
host connector's tool is called by the host that holds the session's
workspace, as `exec` work: the platform names the server and never opens a
connection to it. Before either, the call checks that a person's review
still serves the tool at the definition the session holds."""

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from pydantic import Field, model_serializer, model_validator

from acme.infra.agent_workspaces import AgentWorkspace
from acme.infra.base import FrozenMapping, thaw_mapping
from acme.infra.secrets import SecretsInterface
from acme.integrations.mcp import McpAnswer, McpClientInterface
from acme.om.agent_projects.policies import SessionAgentProjectsInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_steps.types.header import ToolFailure
from acme.om.agents.attached import Attached, AttachedToolsetsInterface
from acme.om.agents.types.kind import AgentKindCatalog
from acme.om.base import utcnow
from acme.om.connectors.impl.addresses import Resolve, refused_now, resolve
from acme.om.connectors.impl.manager import ConnectorsOptions
from acme.om.connectors.rules import cloud_server, pinned, still_reviewed, toolset_of
from acme.om.connectors.storage import ConnectorStorageInterface
from acme.om.connectors.types.connector import (
    AgentSessionConnectors,
    Connector,
    ConnectorPlace,
    ConnectorTool,
    PinnedConnector,
)
from acme.om.context import TenantContext
from acme.om.exceptions import ToolFailed
from acme.om.exec_relay.types.exec import McpRequest
from acme.om.tools.mcp import McpCall, McpServers, secret_use
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.mcp import McpBinding
from acme.om.tools.types.tool import Effect, ToolInput
from acme.om.tools.types.toolset import Toolset
from acme.om.trust.placement import PlacementInterface

CALL_TIMEOUT = timedelta(seconds=60)
"""How long one call of a server's tool may take, its listing included."""

ToolOf = Callable[..., ToolInterface]
"""Builds the tool of a binding over a server's definition, its call, and
the secret its spec declares: the engine's `McpToolImpl`, as a root wires
it."""


class HostCall(Protocol):
    """Reaches a tool of a server the host that holds `workspace` runs, as
    `exec` work keyed by the call: the runner's exec relay transport."""

    def __call__(
        self,
        workspace: AgentWorkspace,
        request: McpRequest,
        *,
        key: UUID,
        effect: Effect,
        deadline: datetime,
        epoch: int,
    ) -> Awaitable[McpAnswer]: ...


class ServerInput(ToolInput):
    """A server's tool's input: the object the model wrote, held whole and
    passed on whole. The server holds it to the schema it listed, which is
    the one the model reads, and its refusal is the call's failure the
    model reads. An input that is not an object is refused here."""

    arguments: FrozenMapping = Field(default_factory=dict, validate_default=True)

    @model_validator(mode="before")
    @classmethod
    def _held_whole(cls, data: Any) -> Any:
        return {"arguments": data}

    @model_serializer(mode="plain")
    def _the_arguments(self) -> dict[str, Any]:
        return thaw_mapping(self.arguments)


def input_model_of(schema: Mapping[str, Any]) -> type[ToolInput]:
    """The input of a tool whose schema is a server's, as a person reviewed
    it: rendered as the server wrote it."""
    plain = thaw_mapping(schema)

    class Input(ServerInput):
        @classmethod
        def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return thaw_mapping(plain)

    return Input


class ConnectorToolsetsImpl(AttachedToolsetsInterface):
    """`host` reaches a server inside a customer's wall; None is a process
    that reaches no host, whose calls of such a server are refused."""

    def __init__(
        self,
        storage: ConnectorStorageInterface,
        kinds: AgentKindCatalog,
        agent_projects: SessionAgentProjectsInterface,
        placement: PlacementInterface,
        client: McpClientInterface,
        secrets: SecretsInterface,
        options: ConnectorsOptions,
        *,
        tool_of: ToolOf,
        host: HostCall | None = None,
        resolver: Resolve = resolve,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._tool_of = tool_of
        self._kinds = kinds
        self._agent_projects = agent_projects
        self._placement = placement
        self._client = client
        self._secrets = secrets
        self._options = options
        self._host = host
        self._resolve = resolver
        self._clock = clock

    async def of(self, ctx: TenantContext, session: AgentSession) -> Attached:
        pin = await self._storage.read_pin(ctx.org_id, session.id)
        if pin is None:
            pin = await self._pin(ctx, session)
        held: list[Toolset] = []
        deferred: list[Toolset] = []
        tools: list[ToolInterface] = []
        for connector in pin.connectors:
            (deferred if connector.deferred else held).append(toolset_of(connector))
            tools.extend(self._tool(connector, tool) for tool in connector.tools)
        return Attached(held=tuple(held), deferred=tuple(deferred), tools=tuple(tools))

    async def _pin(self, ctx: TenantContext, session: AgentSession) -> AgentSessionConnectors:
        """What the session holds of its tenant's connectors, written once:
        a run that pinned first wins, and every run after reads it."""
        root = session.root_id
        agent_project_id = await self._agent_projects.agent_project_of(ctx, root)
        inside = await self._placement.inside_wall(ctx.org_id, root)
        parent = (
            None
            if session.parent_id is None
            else await self._storage.read_pin(ctx.org_id, session.parent_id)
        )
        kind = self._kinds.get(session.kind, session.kind_version)
        taken = {toolset.name for toolset in (*kind.toolsets, *kind.deferred)}
        connectors = [
            connector
            for connector in await self._connectors(ctx)
            if connector.name not in taken
            and not {tool.name for tool in connector.tools} & set(kind.tools)
        ]
        pin = AgentSessionConnectors(
            id=session.id,
            created_at=self._clock(),
            connectors=pinned(
                connectors,
                session.kind,
                agent_project_id,
                inside_wall=inside,
                parent=parent,
                child=session.parent_id is not None,
            ),
        )
        return await self._storage.create_pin(ctx.org_id, pin)

    async def _connectors(self, ctx: TenantContext) -> list[Connector]:
        found: list[Connector] = []
        after: UUID | None = None
        while True:
            page = await self._storage.read_connectors(ctx.org_id, after, self._options.page)
            found.extend(page)
            if len(page) < self._options.page:
                return found
            after = page[-1].id

    def _tool(self, connector: PinnedConnector, tool: ConnectorTool) -> ToolInterface:
        binding = McpBinding(
            server=connector.name,
            server_tool=tool.definition.name,
            name=tool.name,
            input_model=input_model_of(tool.definition.input_schema),
            timeout=CALL_TIMEOUT,
            authorization_class=tool.authorization_class.value,
            effect=tool.effect,
            definition_hash=tool.definition_hash,
        )
        match connector.place:
            case ConnectorPlace.CLOUD:
                server = cloud_server(connector)
                call = self._cloud(
                    connector, tool, McpServers(self._client, self._secrets, (server,))
                )
                return self._tool_of(tool.definition, binding, call, secret=secret_use(server))
            case ConnectorPlace.HOST:
                return self._tool_of(tool.definition, binding, self._on_host(connector, tool))

    def _cloud(
        self, connector: PinnedConnector, tool: ConnectorTool, servers: McpServers
    ) -> McpCall:
        async def call(
            ctx: TenantContext,
            binding: McpBinding,
            call_input: Mapping[str, Any],
            runtime: ToolRuntime,
        ) -> str:
            await self._served(ctx, connector, tool)
            refusal = await refused_now(
                connector.url or "", private=self._options.private_addresses, resolver=self._resolve
            )
            if refusal is not None:
                raise ToolFailed(ToolFailure.PERMANENT, f"{binding.name}: {refusal}")
            return await servers.call(ctx, binding, call_input, runtime)

        return call

    def _on_host(self, connector: PinnedConnector, tool: ConnectorTool) -> McpCall:
        async def call(
            ctx: TenantContext,
            binding: McpBinding,
            call_input: Mapping[str, Any],
            runtime: ToolRuntime,
        ) -> str:
            await self._served(ctx, connector, tool)
            if self._host is None or connector.host_server is None:
                raise ToolFailed(
                    ToolFailure.PERMANENT, f"{binding.name}: this process reaches no host"
                )
            request = McpRequest(
                server=connector.host_server,
                tool=tool.definition.name,
                arguments=call_input,
                definition=tool.definition.model_dump(mode="json"),
            )
            answer = await self._host(
                runtime.workspace,
                request,
                key=runtime.key,
                effect=binding.effect,
                deadline=runtime.deadline,
                epoch=runtime.epoch,
            )
            if answer.is_error:
                raise ToolFailed(
                    ToolFailure.PERMANENT,
                    f"{binding.name} failed on {connector.name}: {answer.text}",
                )
            return answer.text

        return call

    async def _served(
        self, ctx: TenantContext, connector: PinnedConnector, tool: ConnectorTool
    ) -> None:
        """Refuses a call of a tool no review serves now at the definition the
        session pinned: a person withdrew it, or reviewed it again."""
        current = await self._storage.read_connector(ctx.org_id, connector.connector_id)
        reason = still_reviewed(current, tool)
        if reason is not None:
            raise ToolFailed(ToolFailure.PERMANENT, reason)
