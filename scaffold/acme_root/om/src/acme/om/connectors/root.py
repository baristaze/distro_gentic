"""The connectors swimlane over the engine's managers, as a root builds it.

    connectors = build_connectors(storage, infra, managers, client=client)

A root that runs loops hands the loop the toolsets each session holds of
its tenant's connectors, which answer once the managers are built, with
the placement that says which side of the wall a session is on and the
relay that reaches the host inside it:

    layer = ConnectorsLayer(storage, infra, client, placement=placement, host=relay.call_mcp)
    options = PlatformRootOptions(attached_toolsets=layer.attached)
    managers = build_platform_managers(storage, infra, ..., platform_root_options=options)
    connectors = layer.build(managers)

A session's agent project is read from the agent projects' rows."""

from collections.abc import Callable
from datetime import datetime

from acme.infra.root import InfraInterface
from acme.integrations.mcp import McpClientInterface
from acme.om.agent_projects.impl.policies import SessionAgentProjectsBoundImpl
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents.attached import Attached, AttachedToolsetsInterface
from acme.om.base import utcnow
from acme.om.connectors.impl.addresses import Resolve, resolve
from acme.om.connectors.impl.manager import ConnectorsManagerImpl, ConnectorsOptions
from acme.om.connectors.impl.toolsets import ConnectorToolsetsImpl, HostCall
from acme.om.connectors.manager import ConnectorsManagerInterface
from acme.om.context import TenantContext
from acme.om.levers.rules import reach_of
from acme.om.platform_root import PlatformManagers
from acme.om.storage.root import StorageInterface
from acme.om.tools.mcp import McpToolImpl
from acme.om.trust.placement import PlacementInterface


def build_connectors(
    storage: StorageInterface,
    infra: InfraInterface,
    managers: PlatformManagers,
    *,
    client: McpClientInterface,
    options: ConnectorsOptions | None = None,
    resolver: Resolve = resolve,
    clock: Callable[[], datetime] = utcnow,
) -> ConnectorsManagerInterface:
    return ConnectorsManagerImpl(
        storage.get_connector_storage(),
        client,
        infra.get_secrets(),
        managers.kinds,
        SessionAgentProjectsBoundImpl(storage.get_agent_project_storage()),
        managers.tenancy,
        managers.outbox,
        options or ConnectorsOptions(),
        reach_of(managers.kinds),
        resolver=resolver,
        clock=clock,
    )


class AttachedToolsetsLateImpl(AttachedToolsetsInterface):
    """The toolsets the impl `late` answers once it is built: a root hands
    the loop this before it builds the managers the impl reads."""

    def __init__(self, late: Callable[[], AttachedToolsetsInterface]) -> None:
        self._late = late

    async def of(self, ctx: TenantContext, session: AgentSession) -> Attached:
        return await self._late().of(ctx, session)


class ConnectorsLayer:
    """The toolsets each session holds of its tenant's connectors, for the
    loop, and the connectors manager, once `build` has built both over the
    managers."""

    def __init__(
        self,
        storage: StorageInterface,
        infra: InfraInterface,
        client: McpClientInterface,
        *,
        placement: PlacementInterface,
        host: HostCall | None = None,
        options: ConnectorsOptions | None = None,
        resolver: Resolve = resolve,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._infra = infra
        self._client = client
        self._placement = placement
        self._host = host
        self._options = options or ConnectorsOptions()
        self._resolve = resolver
        self._clock = clock
        self._built: tuple[ConnectorsManagerInterface, ConnectorToolsetsImpl] | None = None

    @property
    def attached(self) -> AttachedToolsetsInterface:
        """What `PlatformRootOptions` takes as `attached_toolsets`."""
        return AttachedToolsetsLateImpl(lambda: self._parts()[1])

    def build(self, managers: PlatformManagers) -> ConnectorsManagerInterface:
        """The connectors manager over the engine's, once; built again, the same."""
        if self._built is None:
            manager = build_connectors(
                self._storage,
                self._infra,
                managers,
                client=self._client,
                options=self._options,
                resolver=self._resolve,
                clock=self._clock,
            )
            toolsets = ConnectorToolsetsImpl(
                self._storage.get_connector_storage(),
                managers.kinds,
                SessionAgentProjectsBoundImpl(self._storage.get_agent_project_storage()),
                self._placement,
                self._client,
                self._infra.get_secrets(),
                self._options,
                tool_of=McpToolImpl,
                host=self._host,
                resolver=self._resolve,
                clock=self._clock,
            )
            self._built = (manager, toolsets)
        return self._built[0]

    def _parts(self) -> tuple[ConnectorsManagerInterface, ConnectorToolsetsImpl]:
        if self._built is None:
            raise RuntimeError("the connectors layer is used before its manager is built")
        return self._built
