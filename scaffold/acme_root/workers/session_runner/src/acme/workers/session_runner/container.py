"""The runner boots the way every process does: settings, storage, infra,
the integrations (the model providers), and the managers, with the
product's agent kinds and tools. The claim loop holds the container
directly.

The runner holds no purge login: it runs what a model asks for, and the
one login that deletes a history is the maintenance worker's alone."""

import logging
from uuid import UUID

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.root import InfraInterface
from acme.integrations.impl.configured import IntegrationsConfiguredImpl
from acme.integrations.root import IntegrationsInterface
from acme.om.agents.types.kind import AgentKind
from acme.om.attribution.impl.manager import members_context
from acme.om.attribution.types.principal import Principal
from acme.om.automations.root import automation_principals
from acme.om.base import new_id
from acme.om.context import RequestContext, TenantContext
from acme.om.evidence import ExecutorInterface, WorkProductInterface
from acme.om.hosts.impl.placement import PlacementHostsImpl
from acme.om.intake.root import build_intake
from acme.om.knowledge.root import KnowledgeLayer
from acme.om.notifications.manager import NotificationsManagerInterface
from acme.om.notifications.root import build_notifications
from acme.om.playbooks.root import PlaybooksLayer
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
        # Whoever can clear a park its runs wrote is told, on their channels.
        self.notifications: NotificationsManagerInterface = build_notifications(
            storage, managers, integrations, build_intake(storage, managers)
        )

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
        this runner its executor, and refused a secret that would cross its
        session's wall. A session pinned to its tenant's hosts is inside the
        wall, its sub-agents with it, and none of their calls runs on this
        runner."""
        runner = Executor(kind=ExecutorKind.CLOUD, credential_id=new_id(), label=settings.runner_id)
        trust = TrustLayer(
            storage,
            infra,
            placement=PlacementHostsImpl(
                storage.get_hosts_storage(), storage.get_agent_session_storage(), runner
            ),
            probe=KeyProbeAbsentImpl(),
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
            # A call of a session the tenant's automation principal started
            # runs on that principal's grant; every other on a member's place.
            principal_context=automation_principals(storage.get_automation_storage(), members),
        )
        trust.build(managers)
        playbooks.build(managers)
        knowledge.build(managers)
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
