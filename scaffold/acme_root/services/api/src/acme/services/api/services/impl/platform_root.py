"""The platform's services root: the engine's services, which it hands on as
they are, the platform's beside them, and a product's by its namespace's
name, as `build_platform_services` builds them over the managers and the
layers each process builds."""

from collections.abc import Mapping

from acme.infra.root import InfraInterface
from acme.om.agent_automations import AgentAutomationsManagerInterface
from acme.om.agent_billing import AgentBillingManagerInterface
from acme.om.agent_knowledge import AgentKnowledgeManagerInterface
from acme.om.agent_playbooks import AgentPlaybooksManagerInterface
from acme.om.connectors import ConnectorsManagerInterface
from acme.om.intake import IntakeManagerInterface
from acme.om.levers import LeversManagerInterface
from acme.om.matrix.root import MatrixManagers
from acme.om.park_alerts import ParkAlertsManagerInterface
from acme.om.platform_root import PlatformManagers
from acme.om.trust import TrustManagerInterface, TrustOperatorManagerInterface
from acme.om.watch import WatchManagerInterface
from acme.services.api.services import ServicesInterface
from acme.services.api.services.admin import AdminServiceInterface
from acme.services.api.services.agent_automations import AgentAutomationsServiceInterface
from acme.services.api.services.agent_billing import AgentBillingServiceInterface
from acme.services.api.services.agent_fleet import AgentFleetServiceInterface
from acme.services.api.services.agent_knowledge import AgentKnowledgeServiceInterface
from acme.services.api.services.agent_playbooks import AgentPlaybooksServiceInterface
from acme.services.api.services.agent_projects import AgentProjectsServiceInterface
from acme.services.api.services.agent_sessions import AgentSessionsServiceInterface
from acme.services.api.services.benchmarks import BenchmarksServiceInterface
from acme.services.api.services.budgets import BudgetsServiceInterface
from acme.services.api.services.connectors import ConnectorsServiceInterface
from acme.services.api.services.events import ChangeEventsServiceInterface
from acme.services.api.services.evidence import EvidenceServiceInterface
from acme.services.api.services.exec_relay import ExecRelayServiceInterface
from acme.services.api.services.flags import FlagsServiceInterface
from acme.services.api.services.hosts import HostsServiceInterface
from acme.services.api.services.impl.agent_automations import AgentAutomationsServiceImpl
from acme.services.api.services.impl.agent_billing import AgentBillingServiceImpl
from acme.services.api.services.impl.agent_fleet import AgentFleetServiceImpl
from acme.services.api.services.impl.agent_knowledge import AgentKnowledgeServiceImpl
from acme.services.api.services.impl.agent_playbooks import AgentPlaybooksServiceImpl
from acme.services.api.services.impl.agent_projects import AgentProjectsServiceImpl
from acme.services.api.services.impl.benchmarks import BenchmarksServiceImpl
from acme.services.api.services.impl.budgets import BudgetsServiceImpl
from acme.services.api.services.impl.connectors import ConnectorsServiceImpl
from acme.services.api.services.impl.evidence import EvidenceServiceImpl
from acme.services.api.services.impl.exec_relay import ExecRelayServiceImpl
from acme.services.api.services.impl.hosts import HostsServiceImpl
from acme.services.api.services.impl.intake import IntakeServiceImpl
from acme.services.api.services.impl.matrix import MatrixServiceImpl
from acme.services.api.services.impl.park_alerts import ParkAlertsServiceImpl
from acme.services.api.services.impl.provider_keys import ProviderKeysServiceImpl
from acme.services.api.services.impl.retention import RetentionServiceImpl
from acme.services.api.services.impl.spend_ledgers import SpendLedgersServiceImpl
from acme.services.api.services.impl.tools import ToolsServiceImpl
from acme.services.api.services.impl.validations import ValidationsServiceImpl
from acme.services.api.services.impl.watch import WatchServiceImpl
from acme.services.api.services.intake import IntakeServiceInterface
from acme.services.api.services.leases import LeasesServiceInterface
from acme.services.api.services.matrix import MatrixServiceInterface
from acme.services.api.services.media import MediaServiceInterface
from acme.services.api.services.park_alerts import ParkAlertsServiceInterface
from acme.services.api.services.platform import PlatformServicesInterface
from acme.services.api.services.provider_keys import ProviderKeysServiceInterface
from acme.services.api.services.realtime import RealtimeServiceInterface
from acme.services.api.services.retention import RetentionServiceInterface
from acme.services.api.services.spend_ledgers import SpendLedgersServiceInterface
from acme.services.api.services.tenancy import TenancyServiceInterface
from acme.services.api.services.tools import ToolsServiceInterface
from acme.services.api.services.validations import ValidationsServiceInterface
from acme.services.api.services.watch import WatchServiceInterface
from acme.services.api.services.webhooks import WebhooksServiceInterface


class PlatformServicesImpl(PlatformServicesInterface):
    def __init__(
        self,
        engine: ServicesInterface,
        hosts: HostsServiceInterface,
        agent_fleet: AgentFleetServiceInterface,
        exec_relay: ExecRelayServiceInterface,
        intake: IntakeServiceInterface,
        budgets: BudgetsServiceInterface,
        agent_billing: AgentBillingServiceInterface,
        agent_automations: AgentAutomationsServiceInterface,
        park_alerts: ParkAlertsServiceInterface,
        watch: WatchServiceInterface,
        matrix: MatrixServiceInterface,
        provider_keys: ProviderKeysServiceInterface,
        benchmarks: BenchmarksServiceInterface,
        spend_ledgers: SpendLedgersServiceInterface,
        evidence: EvidenceServiceInterface,
        agent_projects: AgentProjectsServiceInterface,
        agent_knowledge: AgentKnowledgeServiceInterface,
        agent_playbooks: AgentPlaybooksServiceInterface,
        connectors: ConnectorsServiceInterface,
        tools: ToolsServiceInterface,
        retention: RetentionServiceInterface,
        validations: ValidationsServiceInterface,
        products: Mapping[str, object],
    ) -> None:
        # The engine's services, as its root built them.
        self._tenancy = engine.get_tenancy_service()
        self._admin = engine.get_admin_service()
        self._change_events = engine.get_change_events_service()
        self._media = engine.get_media_service()
        self._flags = engine.get_flags_service()
        self._realtime = engine.get_realtime_service()
        self._webhooks = engine.get_webhooks_service()
        self._leases = engine.get_lease_service()
        self._agent_sessions = engine.get_agent_sessions_service()
        self._hosts = hosts
        self._agent_fleet = agent_fleet
        self._exec_relay = exec_relay
        self._intake = intake
        self._budgets = budgets
        self._agent_billing = agent_billing
        self._agent_automations = agent_automations
        self._park_alerts = park_alerts
        self._watch = watch
        self._matrix = matrix
        self._provider_keys = provider_keys
        self._benchmarks = benchmarks
        self._spend_ledgers = spend_ledgers
        self._evidence = evidence
        self._agent_projects = agent_projects
        self._agent_knowledge = agent_knowledge
        self._agent_playbooks = agent_playbooks
        self._connectors = connectors
        self._tools = tools
        self._retention = retention
        self._validations = validations
        self._products = dict(products)

    def get_tenancy_service(self) -> TenancyServiceInterface:
        return self._tenancy

    def get_admin_service(self) -> AdminServiceInterface:
        return self._admin

    def get_change_events_service(self) -> ChangeEventsServiceInterface:
        return self._change_events

    def get_media_service(self) -> MediaServiceInterface:
        return self._media

    def get_flags_service(self) -> FlagsServiceInterface:
        return self._flags

    def get_realtime_service(self) -> RealtimeServiceInterface:
        return self._realtime

    def get_webhooks_service(self) -> WebhooksServiceInterface:
        return self._webhooks

    def get_lease_service(self) -> LeasesServiceInterface:
        return self._leases

    def get_agent_sessions_service(self) -> AgentSessionsServiceInterface:
        return self._agent_sessions

    def get_hosts_service(self) -> HostsServiceInterface:
        return self._hosts

    def get_agent_fleet_service(self) -> AgentFleetServiceInterface:
        return self._agent_fleet

    def get_exec_relay_service(self) -> ExecRelayServiceInterface:
        return self._exec_relay

    def get_intake_service(self) -> IntakeServiceInterface:
        return self._intake

    def get_budgets_service(self) -> BudgetsServiceInterface:
        return self._budgets

    def get_agent_billing_service(self) -> AgentBillingServiceInterface:
        return self._agent_billing

    def get_agent_automations_service(self) -> AgentAutomationsServiceInterface:
        return self._agent_automations

    def get_park_alerts_service(self) -> ParkAlertsServiceInterface:
        return self._park_alerts

    def get_watch_service(self) -> WatchServiceInterface:
        return self._watch

    def get_matrix_service(self) -> MatrixServiceInterface:
        return self._matrix

    def get_provider_keys_service(self) -> ProviderKeysServiceInterface:
        return self._provider_keys

    def get_benchmarks_service(self) -> BenchmarksServiceInterface:
        return self._benchmarks

    def get_spend_ledgers_service(self) -> SpendLedgersServiceInterface:
        return self._spend_ledgers

    def get_evidence_service(self) -> EvidenceServiceInterface:
        return self._evidence

    def get_agent_projects_service(self) -> AgentProjectsServiceInterface:
        return self._agent_projects

    def get_agent_knowledge_service(self) -> AgentKnowledgeServiceInterface:
        return self._agent_knowledge

    def get_agent_playbooks_service(self) -> AgentPlaybooksServiceInterface:
        return self._agent_playbooks

    def get_connectors_service(self) -> ConnectorsServiceInterface:
        return self._connectors

    def get_tools_service(self) -> ToolsServiceInterface:
        return self._tools

    def get_retention_service(self) -> RetentionServiceInterface:
        return self._retention

    def get_validations_service(self) -> ValidationsServiceInterface:
        return self._validations

    def get_product_services(self) -> Mapping[str, object]:
        return self._products


def build_platform_services(
    engine: ServicesInterface,
    managers: PlatformManagers,
    infra: InfraInterface,
    watch: WatchManagerInterface,
    trust_operator: TrustOperatorManagerInterface,
    *,
    intake: IntakeManagerInterface,
    agent_automations: AgentAutomationsManagerInterface,
    park_alerts: ParkAlertsManagerInterface,
    matrix: MatrixManagers,
    trust: TrustManagerInterface,
    agent_billing: AgentBillingManagerInterface,
    agent_knowledge: AgentKnowledgeManagerInterface,
    agent_playbooks: AgentPlaybooksManagerInterface,
    levers: LeversManagerInterface,
    connectors: ConnectorsManagerInterface,
    products: Mapping[str, object],
) -> PlatformServicesInterface:
    """The engine's services, the platform's over its managers and the
    layers built over them, and `products`, a product's services by its
    namespace's name. In-process impls only, as the engine's are."""
    return PlatformServicesImpl(
        engine,
        hosts=HostsServiceImpl(managers.hosts, managers.cloud_pool),
        agent_fleet=AgentFleetServiceImpl(managers.placement_operator, trust_operator, levers),
        exec_relay=ExecRelayServiceImpl(managers.exec_relay, infra.get_topics()),
        intake=IntakeServiceImpl(intake),
        budgets=BudgetsServiceImpl(managers.spend_budgets, agent_billing),
        agent_billing=AgentBillingServiceImpl(agent_billing),
        agent_automations=AgentAutomationsServiceImpl(agent_automations),
        park_alerts=ParkAlertsServiceImpl(park_alerts),
        watch=WatchServiceImpl(watch),
        matrix=MatrixServiceImpl(matrix.matrix, matrix.matrix_operator),
        provider_keys=ProviderKeysServiceImpl(trust),
        benchmarks=BenchmarksServiceImpl(managers.benchmarks),
        spend_ledgers=SpendLedgersServiceImpl(agent_billing),
        evidence=EvidenceServiceImpl(
            managers.agent_sessions,
            managers.evidence,
            managers.agent_workspaces,
            managers.agent_steps,
            intake,
        ),
        agent_projects=AgentProjectsServiceImpl(managers.agent_projects, managers.agent_workspaces),
        agent_knowledge=AgentKnowledgeServiceImpl(agent_knowledge),
        agent_playbooks=AgentPlaybooksServiceImpl(agent_playbooks),
        connectors=ConnectorsServiceImpl(connectors),
        tools=ToolsServiceImpl(managers.tools),
        retention=RetentionServiceImpl(managers.retention),
        validations=ValidationsServiceImpl(managers.platform_agents, managers.evidence),
        products=products,
    )
