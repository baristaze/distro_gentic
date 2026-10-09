"""The runner boots the way every process does: settings, storage, infra,
the integrations (the model providers), and the managers, with the
product's agent kinds and tools, and the automations the platform
assistant reads. The claim loop holds the container directly.

The runner holds no purge login: it runs what a model asks for, and the
one login that deletes a history is the maintenance worker's alone."""

import logging
from uuid import UUID

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.root import InfraInterface
from acme.infra.transports import TransportInterface
from acme.integrations.impl.configured import IntegrationsConfiguredImpl
from acme.integrations.root import IntegrationsInterface
from acme.om.attribution.impl.manager import members_context
from acme.om.attribution.types.principal import Principal
from acme.om.automations import AutomationsManagerInterface
from acme.om.automations.root import automation_principals, build_automations
from acme.om.base import new_id
from acme.om.billing.root import build_money_gate, refuse_open_money
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.hosts.impl.placement import PlacementHostsImpl
from acme.om.intake import IntakeManagerInterface
from acme.om.intake.root import build_intake
from acme.om.intake.tools import CommentImpl
from acme.om.knowledge.root import KnowledgeLayer
from acme.om.matrix.impl.resolver import MatrixOptions
from acme.om.matrix.root import MatrixLayer
from acme.om.notifications.manager import NotificationsManagerInterface
from acme.om.notifications.root import build_notifications
from acme.om.placement.impl.manager import PlacementOptions
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.settings import shipped_agents
from acme.om.playbooks.root import PlaybooksLayer
from acme.om.product_kinds import PRODUCT_KINDS
from acme.om.relay.impl.placement import PlacementRelayedImpl
from acme.om.relay.impl.transport import TransportPlacedImpl, TransportRelayImpl
from acme.om.root import LOCAL, Managers, PlatformPorts, build_managers
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.root import StorageInterface
from acme.om.tools.attachments import AttachmentReaderInterface
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.trust.impl.keys import KeyProbeAbsentImpl
from acme.om.trust.root import TrustLayer
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.watch.root import build_stream
from acme.om.watch.stream import StreamServiceInterface
from acme.om.workspaces.impl.executor import ExecutorOptions
from acme.workers.session_runner.settings import SessionRunnerSettings

log = logging.getLogger(__name__)


class RunnerContainer:
    def __init__(
        self,
        settings: SessionRunnerSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        integrations: IntegrationsInterface,
        managers: Managers,
        stream: StreamServiceInterface,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.integrations = integrations
        self.managers = managers
        # The loop's stream sink: what it streams, on the shared cache.
        self.stream = stream
        # Where a session's acts through the platform's account are recorded;
        # whoever can clear a park its runs wrote is told, on their channels.
        self.intake: IntakeManagerInterface = build_intake(
            storage, managers, integrations=integrations
        )
        self.notifications: NotificationsManagerInterface = build_notifications(
            storage, managers, integrations, self.intake
        )

    @classmethod
    def build(
        cls,
        settings: SessionRunnerSettings,
        *,
        attachment_reader: AttachmentReaderInterface | None = None,
        ports: PlatformPorts | None = None,
    ) -> RunnerContainer:
        """Over the database, the infra, and the providers the settings
        name. `attachment_reader` reads an attachment's text for the
        engine's read tool, and None refuses every read. `ports` are the
        product's, among them the evidence's executor and work product;
        None hands the root `PRODUCT_KINDS` and the platform's own ports,
        and a product that sets ports of its own sets `kinds=PRODUCT_KINDS`
        among them, so every process knows the same kinds. The result gate
        every success passes is the evidence's, over that work product: with
        none wired, no success counts."""
        storage = StoragePostgresImpl(
            settings.role_urls(),
            settings.role_pools(),
            system_urls=settings.system_role_urls(),
        )
        infra = InfraConfiguredImpl(settings)
        integrations = IntegrationsConfiguredImpl(
            settings, settings.environment, settings.is_cloud_environment
        )
        return cls.over(
            settings,
            storage,
            infra,
            integrations,
            attachment_reader=attachment_reader,
            ports=ports or PlatformPorts(kinds=PRODUCT_KINDS),
            platform_agents=shipped_agents(settings, settings.environment),
        )

    @classmethod
    def over(
        cls,
        settings: SessionRunnerSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        integrations: IntegrationsInterface,
        *,
        attachment_reader: AttachmentReaderInterface | None = None,
        ports: PlatformPorts | None = None,
        platform_agents: PlatformAgents | None = None,
        placement_options: PlacementOptions | None = None,
    ) -> RunnerContainer:
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

        Every model call passes billing's money gate, which asks who pays
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
        runner = Executor(kind=ExecutorKind.CLOUD, credential_id=new_id(), label=settings.runner_id)
        placement = PlacementRelayedImpl(
            PlacementHostsImpl(
                storage.get_hosts_storage(), storage.get_agent_session_storage(), runner
            ),
            storage.get_relay_storage(),
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
        playbooks = PlaybooksLayer(storage)
        knowledge = KnowledgeLayer(storage)

        def layers(inner: ToolsManagerInterface) -> ToolsManagerInterface:
            # The wall and the audit first, then the session's playbook gates,
            # then the knowledge a session recalls as its first loop starts.
            return knowledge.tools(playbooks.tools(trust.tools(inner)))

        async def members(
            rctx: RequestContext, org_id: UUID, principal: Principal
        ) -> TenantContext:
            return await members_context(managers.tenancy)(rctx, org_id, principal)

        app = AppContext(type=AppType.WORKER, version=f"{settings.service_name}@{settings.version}")
        built: list[Managers] = []
        held: list[RunnerContainer] = []
        # The tools through which a session acts as the platform's account
        # record each act with intake, and the engineer's pull request binds
        # its work there; the container builds it below.
        acts = (CommentImpl(lambda: held[0].intake, integrations.get_integration),)
        # The automations the platform assistant reads, built below over the
        # managers, as the API and the maintenance worker build them.
        automations: list[AutomationsManagerInterface] = []

        def stage() -> RequestContext:
            """The request stage each relayed operation runs under, minted
            here at the runner's edge, as its claim loop mints one a claim."""
            return RequestContext(request_id=new_id(), app=app)

        def placed(direct: TransportInterface) -> TransportInterface:
            # The relay is the managers', built below on this transport, so
            # the edge is bound at call time.
            relayed = TransportRelayImpl(lambda: built[0].relay, stage)
            return TransportPlacedImpl(direct, relayed, placement)

        # Every part the loop streams goes to the shared cache, where the API
        # reads it live; a stream's opening and its completion are recorded,
        # in the managers' event stream, and hinted.
        stream = build_stream(infra, lambda: built[0].events, product_kinds=ports.kinds)
        managers = build_managers(
            storage,
            infra,
            integrations=integrations,
            environment=settings.environment,
            tool_catalog=acts,
            attachment_reader=attachment_reader,
            platform_agents=platform_agents,
            intake=lambda: held[0].intake,
            knowledge=knowledge.manager,
            automations=lambda: automations[0],
            budget_gate=ports.budget_gate or build_money_gate(storage),
            result_gate=ports.result_gate,
            executor=ports.executor,
            executor_options=ExecutorOptions(image=settings.workspace_image),
            work_product=ports.work_product,
            session_projects=ports.session_projects,
            workspace_projects=ports.workspace_projects,
            product_kinds=ports.kinds,
            models_layer=matrix.layer,
            tools_layer=layers,
            transport_layer=placed,
            placement_options=placement_options,
            # A call of a session the tenant's automation principal started
            # runs on that principal's grant; every other on a member's place.
            principal_context=automation_principals(storage.get_automation_storage(), members),
            stream_sink=stream,
        )
        built.append(managers)
        automations.append(
            build_automations(
                storage,
                managers,
                project_required=settings.environment != LOCAL,
                actions=ports.kinds.actions,
            )
        )
        refuse_open_money(settings.environment, managers)
        trust.build(managers)
        matrix.build(managers)
        playbooks.build(managers)
        knowledge.build(managers)
        container = cls(settings, storage, infra, integrations, managers, stream)
        held.append(container)
        return container

    async def start(self) -> None:
        await self.infra.start()
        await self.integrations.start()
        log.info(
            "%s %s started with %s",
            self.settings.service_name,
            self.settings.runner_id,
            ", ".join([*self.infra.describe(), *self.integrations.describe()]),
        )

    async def close(self) -> None:
        await self.stream.close()
        await self.integrations.close()
        await self.infra.close()
        await self.storage.close()
