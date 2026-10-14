"""Composes one service impl per hosted namespace over the managers and
hands back the network-layer root the container holds."""

from datetime import timedelta

from acme.infra.root import InfraInterface
from acme.integrations.root import IntegrationsInterface
from acme.om.agent_automations import AgentAutomationsManagerInterface
from acme.om.agent_billing import AgentBillingManagerInterface
from acme.om.agent_knowledge import AgentKnowledgeManagerInterface
from acme.om.agent_playbooks import AgentPlaybooksManagerInterface
from acme.om.connectors import ConnectorsManagerInterface
from acme.om.intake import IntakeManagerInterface
from acme.om.levers import LeversManagerInterface
from acme.om.matrix.root import MatrixManagers
from acme.om.park_alerts import ParkAlertsManagerInterface
from acme.om.root import Managers
from acme.om.trust import TrustManagerInterface, TrustOperatorManagerInterface
from acme.om.watch import WatchManagerInterface
from acme.services.api.services import (
    AdminServiceInterface,
    AgentFleetServiceInterface,
    AgentSessionsServiceInterface,
    EventsServiceInterface,
    EvidenceServiceInterface,
    FlagsServiceInterface,
    HostsServiceInterface,
    LeasesServiceInterface,
    MediaServiceInterface,
    RealtimeServiceInterface,
    RelayServiceInterface,
    ServicesInterface,
    TenancyServiceInterface,
    WatchServiceInterface,
    WebhooksServiceInterface,
)
from acme.services.api.services.agent_automations import AgentAutomationsServiceInterface
from acme.services.api.services.agent_billing import AgentBillingServiceInterface
from acme.services.api.services.agent_knowledge import AgentKnowledgeServiceInterface
from acme.services.api.services.agent_playbooks import AgentPlaybooksServiceInterface
from acme.services.api.services.benchmarks import BenchmarksServiceInterface
from acme.services.api.services.budgets import BudgetsServiceInterface
from acme.services.api.services.connectors import ConnectorsServiceInterface
from acme.services.api.services.impl.admin import AdminServiceImpl
from acme.services.api.services.impl.agent_automations import AgentAutomationsServiceImpl
from acme.services.api.services.impl.agent_billing import AgentBillingServiceImpl
from acme.services.api.services.impl.agent_fleet import AgentFleetServiceImpl
from acme.services.api.services.impl.agent_knowledge import AgentKnowledgeServiceImpl
from acme.services.api.services.impl.agent_playbooks import AgentPlaybooksServiceImpl
from acme.services.api.services.impl.agent_sessions import AgentSessionsServiceImpl
from acme.services.api.services.impl.benchmarks import BenchmarksServiceImpl
from acme.services.api.services.impl.budgets import BudgetsServiceImpl
from acme.services.api.services.impl.connectors import ConnectorsServiceImpl
from acme.services.api.services.impl.events import EventsServiceImpl
from acme.services.api.services.impl.evidence import EvidenceServiceImpl
from acme.services.api.services.impl.flags import FlagsServiceImpl
from acme.services.api.services.impl.hosts import HostsServiceImpl
from acme.services.api.services.impl.intake import IntakeServiceImpl
from acme.services.api.services.impl.leases import LeasesServiceImpl
from acme.services.api.services.impl.matrix import MatrixServiceImpl
from acme.services.api.services.impl.media import MediaServiceImpl
from acme.services.api.services.impl.park_alerts import ParkAlertsServiceImpl
from acme.services.api.services.impl.projects import ProjectsServiceImpl
from acme.services.api.services.impl.provider_keys import ProviderKeysServiceImpl
from acme.services.api.services.impl.realtime import RealtimeServiceImpl
from acme.services.api.services.impl.relay import RelayServiceImpl
from acme.services.api.services.impl.retention import RetentionServiceImpl
from acme.services.api.services.impl.spend_ledgers import SpendLedgersServiceImpl
from acme.services.api.services.impl.tenancy import TenancyServiceImpl
from acme.services.api.services.impl.tools import ToolsServiceImpl
from acme.services.api.services.impl.validations import ValidationsServiceImpl
from acme.services.api.services.impl.watch import WatchServiceImpl
from acme.services.api.services.impl.webhooks import WebhooksServiceImpl
from acme.services.api.services.intake import IntakeServiceInterface
from acme.services.api.services.matrix import MatrixServiceInterface
from acme.services.api.services.park_alerts import ParkAlertsServiceInterface
from acme.services.api.services.projects import ProjectsServiceInterface
from acme.services.api.services.provider_keys import ProviderKeysServiceInterface
from acme.services.api.services.retention import RetentionServiceInterface
from acme.services.api.services.spend_ledgers import SpendLedgersServiceInterface
from acme.services.api.services.tools import ToolsServiceInterface
from acme.services.api.services.validations import ValidationsServiceInterface


class ServicesImpl(ServicesInterface):
    def __init__(
        self,
        tenancy: TenancyServiceInterface,
        admin: AdminServiceInterface,
        events: EventsServiceInterface,
        media: MediaServiceInterface,
        flags: FlagsServiceInterface,
        realtime: RealtimeServiceInterface,
        webhooks: WebhooksServiceInterface,
        leases: LeasesServiceInterface,
        agent_sessions: AgentSessionsServiceInterface,
        hosts: HostsServiceInterface,
        agent_fleet: AgentFleetServiceInterface,
        relay: RelayServiceInterface,
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
        projects: ProjectsServiceInterface,
        agent_knowledge: AgentKnowledgeServiceInterface,
        agent_playbooks: AgentPlaybooksServiceInterface,
        connectors: ConnectorsServiceInterface,
        tools: ToolsServiceInterface,
        retention: RetentionServiceInterface,
        validations: ValidationsServiceInterface,
    ) -> None:
        self._tenancy = tenancy
        self._admin = admin
        self._events = events
        self._media = media
        self._flags = flags
        self._realtime = realtime
        self._webhooks = webhooks
        self._leases = leases
        self._agent_sessions = agent_sessions
        self._hosts = hosts
        self._agent_fleet = agent_fleet
        self._relay = relay
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
        self._projects = projects
        self._agent_knowledge = agent_knowledge
        self._agent_playbooks = agent_playbooks
        self._connectors = connectors
        self._tools = tools
        self._retention = retention
        self._validations = validations

    def get_tenancy_service(self) -> TenancyServiceInterface:
        return self._tenancy

    def get_admin_service(self) -> AdminServiceInterface:
        return self._admin

    def get_events_service(self) -> EventsServiceInterface:
        return self._events

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

    def get_relay_service(self) -> RelayServiceInterface:
        return self._relay

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

    def get_projects_service(self) -> ProjectsServiceInterface:
        return self._projects

    def get_agent_knowledge_service(self) -> AgentKnowledgeServiceInterface:
        return self._agent_knowledge

    def get_connectors_service(self) -> ConnectorsServiceInterface:
        return self._connectors

    def get_agent_playbooks_service(self) -> AgentPlaybooksServiceInterface:
        return self._agent_playbooks

    def get_tools_service(self) -> ToolsServiceInterface:
        return self._tools

    def get_retention_service(self) -> RetentionServiceInterface:
        return self._retention

    def get_validations_service(self) -> ValidationsServiceInterface:
        return self._validations


def build_services(
    managers: Managers,
    infra: InfraInterface,
    integrations: IntegrationsInterface,
    head_max_age: timedelta,
    watch: WatchManagerInterface,
    trust_operator: TrustOperatorManagerInterface,
    *,
    project_required: bool,
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
) -> ServicesInterface:
    """In-process impls only: a Python caller outside the process reaches the
    same services through the typed client under `clients/python`."""
    return ServicesImpl(
        tenancy=TenancyServiceImpl(managers.tenancy),
        admin=AdminServiceImpl(
            managers.tenancy_operator, managers.work_operator, managers.budgets_operator
        ),
        events=EventsServiceImpl(managers.events),
        media=MediaServiceImpl(managers.media),
        flags=FlagsServiceImpl(infra.get_flags()),
        realtime=RealtimeServiceImpl(
            managers.tenancy, managers.events, infra.get_topics(), head_max_age
        ),
        webhooks=WebhooksServiceImpl(
            integrations.get_identity_provider(),
            infra.get_queues(),
            integrations.get_integration,
            intake,
        ),
        leases=LeasesServiceImpl(managers.leases),
        agent_sessions=AgentSessionsServiceImpl(
            managers.agent_sessions,
            managers.agents,
            managers.steps,
            managers.tools,
            managers.attribution,
            managers.loop,
            managers.windows,
            managers.projects,
            project_required=project_required,
        ),
        hosts=HostsServiceImpl(managers.hosts, managers.cloud_pool),
        agent_fleet=AgentFleetServiceImpl(managers.placement_operator, trust_operator, levers),
        relay=RelayServiceImpl(managers.relay, infra.get_topics()),
        intake=IntakeServiceImpl(intake),
        budgets=BudgetsServiceImpl(managers.budgets, agent_billing),
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
            managers.workspaces,
            managers.steps,
            intake,
        ),
        projects=ProjectsServiceImpl(managers.projects, managers.workspaces),
        agent_knowledge=AgentKnowledgeServiceImpl(agent_knowledge),
        agent_playbooks=AgentPlaybooksServiceImpl(agent_playbooks),
        connectors=ConnectorsServiceImpl(connectors),
        tools=ToolsServiceImpl(managers.tools),
        retention=RetentionServiceImpl(managers.retention),
        validations=ValidationsServiceImpl(managers.platform_agents, managers.evidence),
    )
