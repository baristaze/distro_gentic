"""The platform's half of the API's container: the managers the platform's
root builds, every layer the platform builds over them in this process, and
the services, the engine's beside the platform's and the product's
(`product_api.PRODUCT_API`), each product service over the live parts built
here (`products.ProductLive`). The container calls `build_platform_api` once,
and holds what it answers."""

from dataclasses import dataclass
from datetime import timedelta

from acme.infra.root import InfraInterface
from acme.integrations.mcp.sdk import McpClientSdkImpl
from acme.integrations.payments import PaymentProviderInterface
from acme.integrations.payments.absent import PaymentProviderAbsentImpl
from acme.integrations.root import IntegrationsInterface
from acme.om import product_namespaces
from acme.om.agent_automations import AgentAutomationsManagerInterface
from acme.om.agent_automations.root import build_agent_automations
from acme.om.agent_billing.root import build_agent_billing, build_money_gate, refuse_open_money
from acme.om.agent_knowledge.root import AgentKnowledgeLayer
from acme.om.agent_playbooks.root import AgentPlaybooksLayer
from acme.om.agent_root import LOCAL, AgentRootOptions
from acme.om.agent_workspaces.impl.executor import ExecutorOptions
from acme.om.agents.impl.hooks import LoopHooksNullImpl
from acme.om.base import new_id
from acme.om.connectors.impl.manager import ConnectorsOptions
from acme.om.connectors.root import build_connectors
from acme.om.intake import IntakeManagerInterface
from acme.om.intake.root import build_intake
from acme.om.intake.tools import CommentImpl
from acme.om.levers.root import build_levers
from acme.om.matrix.impl.resolver import MatrixOptions
from acme.om.matrix.root import MatrixLayer
from acme.om.park_alerts.root import build_park_alerts
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_root import (
    PlatformManagers,
    PlatformPorts,
    PlatformRootOptions,
    build_platform_managers,
)
from acme.om.root import TenancyOperatorOptions, TenancyOptions
from acme.om.storage.root import StorageInterface
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.trust import KeyProbeInterface
from acme.om.trust.impl.keys import KeyProbeAbsentImpl, KeyProbeTwinImpl
from acme.om.trust.impl.placement import PlacementCloudImpl
from acme.om.trust.root import TrustLayer
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.watch.impl.manager import WatchOptions
from acme.om.watch.root import build_kind_streams, build_stream, build_watch
from acme.om.watch.stream import StreamServiceInterface
from acme.services.api import product_api
from acme.services.api.assistant import offered
from acme.services.api.products import ProductLive
from acme.services.api.services.impl.platform_root import build_platform_services
from acme.services.api.services.impl.questions import QuestionStreamsImpl
from acme.services.api.services.impl.root import build_services
from acme.services.api.services.platform import PlatformServicesInterface
from acme.services.api.settings import ApiSettings


@dataclass(frozen=True)
class PlatformApi:
    """What the container holds of the platform: its managers, the services
    every router resolves, and the stream service the live reads of this
    process come from, which the container closes."""

    managers: PlatformManagers
    services: PlatformServicesInterface
    stream: StreamServiceInterface


def key_probe(settings: ApiSettings) -> KeyProbeInterface:
    """What asks a provider whether it takes a tenant's key before the key is
    saved. Beside the scripted providers, which stand in for every model and
    are refused outside a local stack, the probe's twin takes every key; with
    no probe configured, the absent one refuses every save, so no key is ever
    saved unasked."""
    if settings.llm_providers == "scripted":
        return KeyProbeTwinImpl()
    return KeyProbeAbsentImpl()


def build_platform_api(
    settings: ApiSettings,
    storage: StorageInterface,
    infra: InfraInterface,
    integrations: IntegrationsInterface,
    tenancy: TenancyOptions,
    operator: TenancyOperatorOptions,
    *,
    ports: PlatformPorts | None = None,
    platform_agents: PlatformAgents | None = None,
    payments: PaymentProviderInterface | None = None,
) -> PlatformApi:
    """The platform's managers, then its layers, then the services, over
    whichever roots the caller chose. `ports` are the platform's ports the
    product sets, None each for the platform's own: agent billing's money
    gate, and the evidence's result gate. `payments` checks a payment a
    tenant posts; None refuses every one. Their `kinds` are the product's: a
    session starts on one of its agent kinds, and the session runner runs its
    loop with the same kinds, since each process's `build` hands its root
    `PRODUCT_KINDS`. A start or a message is checked against the class of
    every tool its registry offers, the product's included, and a registry
    name the catalog cannot class is refused. Outside `local`, a quiet null
    for any of them, or a budget gate that is not the money gate, is refused
    at boot. `platform_agents` ships the platform's agents beside the
    product's kinds: a deployed process reads them from its corpus root, and
    refuses to boot with none. The session runner's `comment` joins the
    catalog over the intake built here, so a kind that names it starts and
    is messaged."""
    ports = ports or PlatformPorts()
    held: list[IntakeManagerInterface] = []
    streams = QuestionStreamsImpl()
    # The example assistant, where the environment offers it and the product
    # declares no kind; its tool reads the media manager the root below builds.
    example_kinds, example_tools = offered(
        settings.environment, ports.kinds.agent_kinds, lambda: managers.media
    )
    # A start makes each session with its kind manual.
    agent_playbooks = AgentPlaybooksLayer(storage)
    agent_knowledge = AgentKnowledgeLayer(storage)
    # The agent automations a request kind's readers read, built below over
    # the managers, as the session runner builds them.
    agent_automations: list[AgentAutomationsManagerInterface] = []
    # A tenant's own provider keys, saved and listed here and never read
    # back. A request kind's loop runs its calls here, in the cloud, so
    # its placement names this process.
    api = Executor(kind=ExecutorKind.CLOUD, credential_id=new_id(), label=settings.service_name)
    trust = TrustLayer(
        storage,
        infra,
        placement=PlacementCloudImpl(api),
        probe=key_probe(settings),
        product_kinds=ports.kinds,
    )

    # The model matrix: its versions serve every model role the product's
    # kinds call, beside the platform's own. A request kind's loop takes its
    # fills here, and a tenant on its own keys calls on them through trust,
    # as the session runner's loop does.
    matrix = MatrixLayer(
        storage,
        options=MatrixOptions(environment=settings.environment),
        clients=lambda: trust.managers.provider_clients,
        kinds=ports.kinds.agent_kinds,
    )

    def layers(inner: ToolsManagerInterface) -> ToolsManagerInterface:
        # The wall and the audit first, then the session's agent playbook
        # gates, as the session runner holds every call.
        return agent_playbooks.tools(trust.tools(inner))

    managers = build_platform_managers(
        storage,
        infra,
        tenancy,
        operator,
        integrations,
        platform_root_options=PlatformRootOptions(
            platform_agents=platform_agents,
            executor=ports.executor,
            executor_options=ExecutorOptions(image=settings.agent_workspace_image),
            work_product=ports.work_product,
            agent_session_projects=ports.agent_session_projects,
            workspace_agent_projects=ports.workspace_agent_projects,
            product_kinds=ports.kinds,
            tools_layer=layers,
            agents_layer=agent_playbooks.agents,
            # What a request kind's readers read: the agent knowledge base
            # and the agent automations.
            agent_knowledge=agent_knowledge.manager,
            agent_automations=lambda: agent_automations[0],
            # The agent knowledge a session recalls before its first model
            # call, as the session runner recalls it. No connector's toolset
            # is attached here: the loops this process runs are request
            # kinds', which take none.
            loop_hooks=agent_knowledge.loop_hooks(LoopHooksNullImpl()),
        ),
        agent_root_options=AgentRootOptions(
            environment=settings.environment,
            agent_kinds=example_kinds,
            tool_catalog=(
                CommentImpl(lambda: held[0], integrations.get_integration),
                *example_tools,
            ),
            spend_budget_gate=ports.spend_budget_gate or build_money_gate(storage),
            result_gate=ports.result_gate,
            language_models_layer=matrix.layer,
            # A kind whose loop runs in the request that asks it runs here,
            # and streams to that request.
            stream_sink=streams,
        ),
    )
    # Outside a local stack, a session starts in an agent project.
    agent_project_required = settings.environment != LOCAL
    # A person writes an agent automation here, so a product's action kind
    # is held to its shape when it is saved.
    agent_automations.append(
        build_agent_automations(
            storage,
            managers,
            agent_project_required=agent_project_required,
            actions=ports.kinds.actions,
            agent_playbooks=lambda: agent_playbooks.build(managers),
        )
    )
    refuse_open_money(settings.environment, managers)
    trusted = trust.build(managers)
    matrix_managers = matrix.build(managers)
    # Where a tenant connects a system, and where a person reads and
    # clears what waits on them.
    intake = build_intake(storage, managers, integrations=integrations)
    held.append(intake)
    # The streams the runners write, read from the shared cache.
    stream = build_stream(infra, lambda: managers.change_events, product_kinds=ports.kinds)
    # A product's claimants write its streams for the items they hold, and
    # its own services write the kinds no claimant does.
    kind_streams = build_kind_streams(infra, ports.kinds)
    watch = build_watch(
        managers,
        stream,
        WatchOptions(live_read_key=settings.live_read_key),
        kind_streams=kind_streams,
    )
    engine = build_services(
        managers,
        infra,
        integrations,
        timedelta(seconds=settings.realtime_head_max_age_seconds),
        streams,
        intake=intake,
        agent_projects=managers.agent_projects,
        agent_project_required=agent_project_required,
        kinds=managers.kinds,
        place_locally=managers.hosts.place_locally,
    )
    services = build_platform_services(
        engine,
        managers,
        infra,
        watch,
        trusted.trust_operator,
        intake=intake,
        agent_automations=agent_automations[0],
        park_alerts=build_park_alerts(storage, managers, integrations, intake),
        matrix=matrix_managers,
        trust=trusted.trust,
        # The ledger the operators read and grant units on, and the
        # payments a tenant posts, each checked by the provider's
        # signature: with no provider wired, every one is refused.
        agent_billing=build_agent_billing(
            storage, managers, payments or PaymentProviderAbsentImpl()
        ),
        # A person writes and reviews what sessions recall; the runner
        # recalls them, and so does a request kind's loop here. A person
        # publishes the agent playbooks sessions follow, invokes one into a
        # session, and pins one to a kind.
        agent_knowledge=agent_knowledge.build(managers),
        agent_playbooks=agent_playbooks.build(managers),
        # An operator reads which of them the sessions that stalled reached.
        levers=build_levers(storage),
        # A person connects the tenant's servers and reviews their tools;
        # the runner pins and calls them. A local stack's servers run
        # beside it, so its addresses may be this host's.
        connectors=build_connectors(
            storage,
            infra,
            managers,
            client=McpClientSdkImpl(),
            options=ConnectorsOptions(private_addresses=settings.environment == LOCAL),
        ),
        # A claimant's control stream wakes it to read the kinds it reads.
        kind_streams=kind_streams,
        # Each namespace the product serves, over the managers it builds and
        # the live parts built here.
        products=product_api.PRODUCT_API.services(
            storage,
            managers,
            product_namespaces.PRODUCT_NAMESPACES,
            ProductLive(watch, kind_streams),
        ),
    )
    return PlatformApi(managers, services, stream)
