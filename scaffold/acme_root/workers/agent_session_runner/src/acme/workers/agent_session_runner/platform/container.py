"""The platform's half of the session runner's container: the managers the
platform's root builds, every tool call held to the trust swimlane's rules,
with the platform's layers around the loop, and what the runner holds of the
platform beside them (`RunnerPlatform`). The container calls
`build_runner_platform` once."""

from uuid import UUID

from acme.infra.root import InfraInterface
from acme.infra.transports import TransportInterface
from acme.integrations.mcp.sdk import McpClientSdkImpl
from acme.integrations.root import IntegrationsInterface
from acme.om.agent_automations import AgentAutomationsManagerInterface
from acme.om.agent_automations.root import agent_automation_principals, build_agent_automations
from acme.om.agent_billing.root import build_money_gate, refuse_open_money
from acme.om.agent_knowledge.root import AgentKnowledgeLayer
from acme.om.agent_playbooks.root import AgentPlaybooksLayer
from acme.om.agent_root import LOCAL, AgentRootOptions
from acme.om.agent_workspaces.impl.executor import ExecutorOptions
from acme.om.attribution.impl.manager import members_context
from acme.om.attribution.types.principal import Principal
from acme.om.base import new_id
from acme.om.connectors.impl.manager import ConnectorsOptions
from acme.om.connectors.root import ConnectorsLayer
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.exec_relay.impl.placement import PlacementRelayedImpl
from acme.om.exec_relay.impl.transport import TransportPlacedImpl, TransportRelayImpl
from acme.om.hosts.impl.placement import PlacementHostsImpl
from acme.om.intake import IntakeManagerInterface
from acme.om.intake.root import build_intake
from acme.om.intake.tools import CommentImpl
from acme.om.matrix.impl.resolver import MatrixOptions
from acme.om.matrix.root import MatrixLayer
from acme.om.park_alerts.manager import ParkAlertsManagerInterface
from acme.om.park_alerts.root import build_park_alerts
from acme.om.placement.impl.manager import PlacementOptions
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_root import (
    PlatformManagers,
    PlatformPorts,
    PlatformRootOptions,
    ProductKinds,
    build_platform_managers,
)
from acme.om.storage.root import StorageInterface
from acme.om.tools.attachments import AttachmentReaderInterface
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.trust.impl.keys import KeyProbeAbsentImpl
from acme.om.trust.root import TrustLayer
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.watch.root import build_stream
from acme.om.watch.stream import StreamServiceInterface
from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings
from acme.workers.maintenance.platform.container import cloud_pool_options


class RunnerPlatform:
    """What the runner holds of the platform beside its managers: placement's
    options, as the managers were built with them; the loop's stream sink; the
    product's kinds, whose warm graces the held sweep reads; and intake and
    the park alerts, where a session's acts through the platform's account
    are recorded and whoever can clear a park its runs wrote is told."""

    def __init__(
        self,
        storage: StorageInterface,
        managers: PlatformManagers,
        integrations: IntegrationsInterface,
        stream: StreamServiceInterface,
        placement: PlacementOptions,
        kinds: ProductKinds,
    ) -> None:
        self.placement = placement
        self.stream = stream
        self.kinds = kinds
        self.intake: IntakeManagerInterface = build_intake(
            storage, managers, integrations=integrations
        )
        self.park_alerts: ParkAlertsManagerInterface = build_park_alerts(
            storage, managers, integrations, self.intake
        )

    async def close(self) -> None:
        await self.stream.close()


def build_runner_platform(
    settings: AgentSessionRunnerSettings,
    storage: StorageInterface,
    infra: InfraInterface,
    integrations: IntegrationsInterface,
    *,
    attachment_reader: AttachmentReaderInterface | None = None,
    ports: PlatformPorts | None = None,
    platform_agents: PlatformAgents | None = None,
    placement_options: PlacementOptions | None = None,
) -> tuple[PlatformManagers, RunnerPlatform]:
    """The managers over whichever roots the caller chose, every tool call
    held to the trust swimlane's rules: audited with its four answers,
    and refused a secret that would cross its session's wall. A session
    in the cloud runs on this runner, its executor, through infra's
    transport. A session pinned to its tenant's hosts is inside the wall,
    its sub-agents with it: none of their calls runs on this runner. Its
    workspace is prepared by a host of its pool, which holds it from
    then on; until one does, its loop waits on the resource before any
    model call. Each call, its checkout's included, travels as exec
    work to that host, its executor.

    Every model call passes agent billing's money gate, which asks who pays
    before it holds, and its fills come from the model matrix, whose
    version and the tenant's plan tier its spend and tokens count
    under; a tenant on its own keys calls on them, through trust.
    Outside `local`, a quiet null for any of `ports`, or a budget gate
    that is not the money gate, is refused at boot. `platform_agents`
    ships the platform's agents beside the product's kinds, as the API
    does: a deployed runner reads them from its corpus root, and refuses
    to boot with none. `placement_options` names each plan tier's share,
    the cap the runner's lane passes to the claim; None keeps the
    root's."""
    ports = ports or PlatformPorts()
    placing = placement_options or PlacementOptions()
    runner = Executor(kind=ExecutorKind.CLOUD, credential_id=new_id(), label=settings.runner_id)
    placement = PlacementRelayedImpl(
        PlacementHostsImpl(
            storage.get_hosts_storage(), storage.get_agent_session_storage(), runner
        ),
        storage.get_exec_relay_storage(),
    )
    trust = TrustLayer(
        storage,
        infra,
        placement=placement,
        probe=KeyProbeAbsentImpl(),
        product_kinds=ports.kinds,
    )
    matrix = MatrixLayer(
        storage,
        options=MatrixOptions(environment=settings.environment),
        clients=lambda: trust.managers.provider_clients,
        kinds=ports.kinds.agents,
    )
    agent_playbooks = AgentPlaybooksLayer(storage)
    agent_knowledge = AgentKnowledgeLayer(storage)

    def layers(inner: ToolsManagerInterface) -> ToolsManagerInterface:
        # The wall and the audit first, then the session's agent playbook gates,
        # then the agent knowledge a session recalls as its first loop starts.
        return agent_knowledge.tools(agent_playbooks.tools(trust.tools(inner)))

    async def members(rctx: RequestContext, org_id: UUID, principal: Principal) -> TenantContext:
        return await members_context(managers.tenancy)(rctx, org_id, principal)

    app = AppContext(type=AppType.WORKER, version=f"{settings.service_name}@{settings.version}")
    built: list[PlatformManagers] = []
    held: list[RunnerPlatform] = []
    # The tools through which a session acts as the platform's account
    # record each act with intake, and the software engineer's pull request binds
    # its work there; the container builds it below.
    acts = (CommentImpl(lambda: held[0].intake, integrations.get_integration),)
    # The agent automations the platform assistant reads, built below over the
    # managers, as the API and the maintenance worker build them.
    agent_automations: list[AgentAutomationsManagerInterface] = []

    def stage() -> RequestContext:
        """The request stage each relayed operation runs under, minted
        here at the runner's edge, as its claim loop mints one a claim."""
        return RequestContext(request_id=new_id(), app=app)

    # A session's connectors, pinned as its first run begins: a cloud
    # server called from here, a server inside the wall through the host
    # that holds the session's workspace. A local stack's servers run
    # beside it, so its addresses may be this host's.
    connectors = ConnectorsLayer(
        storage,
        infra,
        McpClientSdkImpl(),
        placement=placement,
        host=TransportRelayImpl(lambda: built[0].exec_relay, stage).call_mcp,
        options=ConnectorsOptions(private_addresses=settings.environment == LOCAL),
    )

    def placed(direct: TransportInterface) -> TransportInterface:
        # The exec relay is the managers', built below on this transport, so
        # the edge is bound at call time.
        relayed = TransportRelayImpl(lambda: built[0].exec_relay, stage)
        # A session on a VM of the cloud pool runs its calls on that
        # VM's host, through the exec relay too.
        return TransportPlacedImpl(
            direct, relayed, placement, lambda spec: built[0].cloud_pool.runs(spec)
        )

    # Every part the loop streams goes to the shared cache, where the API
    # reads it live; a stream's opening and its completion are recorded,
    # in the managers' event stream, and hinted.
    stream = build_stream(infra, lambda: built[0].change_events, product_kinds=ports.kinds)
    managers = build_platform_managers(
        storage,
        infra,
        integrations=integrations,
        # A call of a session the tenant's agent automation principal started
        # runs on that principal's grant; every other on a member's place.
        platform_root_options=PlatformRootOptions(
            platform_agents=platform_agents,
            intake=lambda: held[0].intake,
            agent_knowledge=agent_knowledge.manager,
            agent_automations=lambda: agent_automations[0],
            executor=ports.executor,
            executor_options=ExecutorOptions(image=settings.agent_workspace_image),
            work_product=ports.work_product,
            agent_session_projects=ports.agent_session_projects,
            workspace_agent_projects=ports.workspace_agent_projects,
            product_kinds=ports.kinds,
            tools_layer=layers,
            # A spawn and a hand-off make sessions here, each with its kind's
            # kind manual.
            agents_layer=agent_playbooks.agents,
            transport_layer=placed,
            placement_options=placing,
            cloud_pool_options=cloud_pool_options(settings),
            cloud_pool_stage=stage,
            loop_hooks=connectors.loop_hooks,
        ),
        agent_root_options=AgentRootOptions(
            environment=settings.environment,
            tool_catalog=acts,
            attachment_reader=attachment_reader,
            spend_budget_gate=ports.spend_budget_gate or build_money_gate(storage),
            result_gate=ports.result_gate,
            language_models_layer=matrix.layer,
            principal_context=agent_automation_principals(
                storage.get_agent_automation_storage(), members
            ),
            stream_sink=stream,
        ),
    )
    built.append(managers)
    agent_automations.append(
        build_agent_automations(
            storage,
            managers,
            agent_project_required=settings.environment != LOCAL,
            actions=ports.kinds.actions,
            agent_playbooks=lambda: agent_playbooks.build(managers),
        )
    )
    refuse_open_money(settings.environment, managers)
    trust.build(managers)
    matrix.build(managers)
    agent_playbooks.build(managers)
    agent_knowledge.build(managers)
    connectors.build(managers)
    platform = RunnerPlatform(storage, managers, integrations, stream, placing, ports.kinds)
    held.append(platform)
    return managers, platform
