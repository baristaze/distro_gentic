"""The runner boots the way every process does: settings, storage, infra,
the integrations (the model providers), and the managers, with the
product's agent kinds and tools. The claim loop holds the container
directly.

The runner holds no purge login: it runs what a model asks for, and the
one login that deletes a history is the maintenance worker's alone."""

import logging

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.root import InfraInterface
from acme.infra.transports import TransportInterface
from acme.integrations.impl.configured import IntegrationsConfiguredImpl
from acme.integrations.root import IntegrationsInterface
from acme.om.agents.types.kind import AgentKind
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.evidence import ExecutorInterface, WorkProductInterface
from acme.om.hosts.impl.placement import PlacementHostsImpl
from acme.om.playbooks.root import PlaybooksLayer
from acme.om.relay.impl.placement import PlacementRelayedImpl
from acme.om.relay.impl.transport import TransportPlacedImpl, TransportRelayImpl
from acme.om.root import Managers, build_managers
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.root import StorageInterface
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.tool import ToolInterface
from acme.om.trust.impl.keys import KeyProbeAbsentImpl
from acme.om.trust.root import TrustLayer
from acme.om.trust.types.identities import Executor, ExecutorKind
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
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.integrations = integrations
        self.managers = managers

    @classmethod
    def build(
        cls,
        settings: SessionRunnerSettings,
        *,
        agent_kinds: tuple[AgentKind, ...] = (),
        tool_catalog: tuple[ToolInterface, ...] = (),
        domain_classes: tuple[str, ...] = (),
        executor: ExecutorInterface | None = None,
        work_product: WorkProductInterface | None = None,
    ) -> RunnerContainer:
        """Over the database, the infra, and the providers the settings
        name. `agent_kinds`, `tool_catalog`, and `domain_classes` are the
        product's, as every process that builds the managers passes them;
        so are `executor` and `work_product`, the evidence's ports. The
        result gate every success passes is the evidence's, over that work
        product: with none wired, no success counts."""
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
            agent_kinds=agent_kinds,
            tool_catalog=tool_catalog,
            domain_classes=domain_classes,
            executor=executor,
            work_product=work_product,
        )

    @classmethod
    def over(
        cls,
        settings: SessionRunnerSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        integrations: IntegrationsInterface,
        *,
        agent_kinds: tuple[AgentKind, ...] = (),
        tool_catalog: tuple[ToolInterface, ...] = (),
        domain_classes: tuple[str, ...] = (),
        executor: ExecutorInterface | None = None,
        work_product: WorkProductInterface | None = None,
    ) -> RunnerContainer:
        """The managers over whichever roots the caller chose, every tool call
        held to the trust swimlane's rules: audited with its four answers,
        and refused a secret that would cross its session's wall. A session
        in the cloud runs on this runner, its executor, through infra's
        transport. A session pinned to its tenant's hosts is inside the wall,
        its sub-agents with it: none of their calls runs on this runner. Each
        travels as exec work to the host that holds its workspace, its
        executor, and until one does it is refused."""
        runner = Executor(kind=ExecutorKind.CLOUD, credential_id=new_id(), label=settings.runner_id)
        placement = PlacementRelayedImpl(
            PlacementHostsImpl(
                storage.get_hosts_storage(), storage.get_agent_session_storage(), runner
            ),
            storage.get_relay_storage(),
        )
        trust = TrustLayer(storage, infra, placement=placement, probe=KeyProbeAbsentImpl())
        playbooks = PlaybooksLayer(storage)

        def layers(inner: ToolsManagerInterface) -> ToolsManagerInterface:
            # The wall and the audit first, then the session's playbook gates.
            return playbooks.tools(trust.tools(inner))

        app = AppContext(type=AppType.WORKER, version=f"{settings.service_name}@{settings.version}")
        built: list[Managers] = []

        def stage() -> RequestContext:
            """The request stage each relayed operation runs under, minted
            here at the runner's edge, as its claim loop mints one a claim."""
            return RequestContext(request_id=new_id(), app=app)

        def placed(direct: TransportInterface) -> TransportInterface:
            # The relay is the managers', built below on this transport, so
            # the edge is bound at call time.
            relayed = TransportRelayImpl(lambda: built[0].relay, stage)
            return TransportPlacedImpl(direct, relayed, placement)

        managers = build_managers(
            storage,
            infra,
            integrations=integrations,
            environment=settings.environment,
            agent_kinds=agent_kinds,
            tool_catalog=tool_catalog,
            domain_classes=domain_classes,
            executor=executor,
            work_product=work_product,
            tools_layer=layers,
            transport_layer=placed,
        )
        built.append(managers)
        trust.build(managers)
        playbooks.build(managers)
        return cls(settings, storage, infra, integrations, managers)

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
        await self.integrations.close()
        await self.infra.close()
        await self.storage.close()
