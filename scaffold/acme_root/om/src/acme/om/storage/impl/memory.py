"""The in-memory storage root: the default for unit tests and the fast gate."""

from acme.om.agent_sessions.storage import AgentSessionStorageInterface
from acme.om.agent_sessions.storage.impl.memory import AgentSessionStorageMemoryImpl
from acme.om.agents.storage import AgentStorageInterface
from acme.om.agents.storage.impl.memory import AgentStorageMemoryImpl
from acme.om.attribution.storage import AttributionStorageInterface
from acme.om.attribution.storage.impl.memory import AttributionStorageMemoryImpl
from acme.om.automations.storage import AutomationStorageInterface
from acme.om.automations.storage.impl.memory import AutomationStorageMemoryImpl
from acme.om.benchmarks.storage import BenchmarkStorageInterface
from acme.om.benchmarks.storage.impl.memory import BenchmarkStorageMemoryImpl
from acme.om.billing.storage import AccountStorageInterface, MoneyLedgerStorageInterface
from acme.om.billing.storage.impl.memory import (
    AccountStorageMemoryImpl,
    MoneyLedgerStorageMemoryImpl,
)
from acme.om.budgets.storage import BudgetStorageInterface, LedgerStorageInterface
from acme.om.budgets.storage.impl.memory import BudgetStorageMemoryImpl, LedgerStorageMemoryImpl
from acme.om.events.storage import EventStorageInterface
from acme.om.events.storage.impl.memory import EventStorageMemoryImpl
from acme.om.evidence.storage import EvidenceStorageInterface
from acme.om.evidence.storage.impl.memory import EvidenceStorageMemoryImpl
from acme.om.hosts.storage import HostsStorageInterface
from acme.om.hosts.storage.impl.memory import HostsStorageMemoryImpl
from acme.om.idempotency.storage import IdempotencyStorageInterface
from acme.om.idempotency.storage.impl.memory import IdempotencyStorageMemoryImpl
from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.storage.impl.memory import IntakeStorageMemoryImpl
from acme.om.knowledge.storage import KnowledgeStorageInterface
from acme.om.knowledge.storage.impl.memory import KnowledgeStorageMemoryImpl
from acme.om.matrix.storage import MatrixStorageInterface, MatrixTenantStorageInterface
from acme.om.matrix.storage.impl.memory import (
    MatrixStorageMemoryImpl,
    MatrixTenantStorageMemoryImpl,
)
from acme.om.media.storage import MediaStorageInterface
from acme.om.media.storage.impl.memory import MediaStorageMemoryImpl
from acme.om.models.storage import FillSetStorageInterface
from acme.om.models.storage.impl.memory import FillSetStorageMemoryImpl
from acme.om.notifications.storage import NotificationStorageInterface
from acme.om.notifications.storage.impl.memory import NotificationStorageMemoryImpl
from acme.om.orchestrations.storage import OrchestrationsStorageInterface
from acme.om.orchestrations.storage.impl.memory import OrchestrationsStorageMemoryImpl
from acme.om.outbox.storage import OutboxStorageInterface
from acme.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from acme.om.placement.storage import PlacementStorageInterface
from acme.om.placement.storage.impl.memory import PlacementStorageMemoryImpl
from acme.om.platform_agents.storage import PlatformAgentsStorageInterface
from acme.om.platform_agents.storage.impl.memory import PlatformAgentsStorageMemoryImpl
from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.playbooks.storage.impl.memory import PlaybookStorageMemoryImpl
from acme.om.privacy.storage import PrivacyStorageInterface
from acme.om.privacy.storage.impl.memory import PrivacyStorageMemoryImpl
from acme.om.projects.storage import ProjectStorageInterface
from acme.om.projects.storage.impl.memory import ProjectStorageMemoryImpl
from acme.om.relay.storage import RelayStorageInterface
from acme.om.relay.storage.impl.memory import RelayStorageMemoryImpl
from acme.om.retention.storage import RetentionStorageInterface
from acme.om.retention.storage.impl.memory import RetentionStorageMemoryImpl
from acme.om.steps.storage import StepStorageInterface
from acme.om.steps.storage.impl.memory import StepStorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.storage import TenancyStorageInterface
from acme.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl
from acme.om.tools.storage import ToolStorageInterface
from acme.om.tools.storage.impl.memory import ToolStorageMemoryImpl
from acme.om.trust.storage import TrustStorageInterface
from acme.om.trust.storage.impl.memory import TrustStorageMemoryImpl
from acme.om.windows.storage import WindowStorageInterface
from acme.om.windows.storage.impl.memory import WindowStorageMemoryImpl
from acme.om.work.storage import WorkStorageInterface
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl
from acme.om.workspaces.storage import WorkspaceStorageInterface
from acme.om.workspaces.storage.impl.memory import WorkspaceStorageMemoryImpl


class StorageMemoryImpl(StorageInterface):
    def __init__(self) -> None:
        # The outbox and the markers first: the core-role impls land their
        # outbox rows in the one and fence a re-mint on the other, which is
        # how each impl gets what its Postgres twin reads in its own statement.
        self._outbox = OutboxStorageMemoryImpl()
        self._idempotency = IdempotencyStorageMemoryImpl()
        self._tenancy = TenancyStorageMemoryImpl(self._outbox, self._idempotency)
        self._work = WorkStorageMemoryImpl()
        self._orchestrations = OrchestrationsStorageMemoryImpl(self._outbox)
        self._media = MediaStorageMemoryImpl(self._outbox)
        self._events = EventStorageMemoryImpl()
        self._steps = StepStorageMemoryImpl()
        self._agent_sessions = AgentSessionStorageMemoryImpl(self._outbox)
        self._agents = AgentStorageMemoryImpl(self._outbox)
        self._attribution = AttributionStorageMemoryImpl(self._outbox)
        self._privacy = PrivacyStorageMemoryImpl(self._outbox)
        self._projects = ProjectStorageMemoryImpl(self._outbox)
        self._retention = RetentionStorageMemoryImpl(self._outbox)
        self._budgets = BudgetStorageMemoryImpl(self._outbox)
        self._ledger = LedgerStorageMemoryImpl()
        self._accounts = AccountStorageMemoryImpl(self._outbox)
        self._money_ledger = MoneyLedgerStorageMemoryImpl()
        self._fill_sets = FillSetStorageMemoryImpl()
        self._windows = WindowStorageMemoryImpl()
        self._tools = ToolStorageMemoryImpl(self._outbox)
        self._evidence = EvidenceStorageMemoryImpl(self._outbox)
        self._placement = PlacementStorageMemoryImpl()
        self._trust = TrustStorageMemoryImpl(self._outbox)
        self._hosts = HostsStorageMemoryImpl(self._outbox)
        self._intake = IntakeStorageMemoryImpl()
        self._automation = AutomationStorageMemoryImpl(self._outbox)
        self._playbook = PlaybookStorageMemoryImpl(self._outbox)
        self._knowledge = KnowledgeStorageMemoryImpl(self._outbox)
        self._notification = NotificationStorageMemoryImpl()
        self._platform_agents = PlatformAgentsStorageMemoryImpl(self._outbox)
        self._benchmarks = BenchmarkStorageMemoryImpl()
        self._relay = RelayStorageMemoryImpl(self._outbox)
        self._workspaces = WorkspaceStorageMemoryImpl(self._outbox)
        self._matrix = MatrixStorageMemoryImpl()
        self._matrix_tenants = MatrixTenantStorageMemoryImpl()

    def get_tenancy_storage(self) -> TenancyStorageInterface:
        return self._tenancy

    def get_work_storage(self) -> WorkStorageInterface:
        return self._work

    def get_media_storage(self) -> MediaStorageInterface:
        return self._media

    def get_idempotency_storage(self) -> IdempotencyStorageInterface:
        return self._idempotency

    def get_event_storage(self) -> EventStorageInterface:
        return self._events

    def get_outbox_storage(self) -> OutboxStorageInterface:
        return self._outbox

    def get_orchestrations_storage(self) -> OrchestrationsStorageInterface:
        return self._orchestrations

    def get_step_storage(self) -> StepStorageInterface:
        return self._steps

    def get_agent_session_storage(self) -> AgentSessionStorageInterface:
        return self._agent_sessions

    def get_agent_storage(self) -> AgentStorageInterface:
        return self._agents

    def get_attribution_storage(self) -> AttributionStorageInterface:
        return self._attribution

    def get_privacy_storage(self) -> PrivacyStorageInterface:
        return self._privacy

    def get_project_storage(self) -> ProjectStorageInterface:
        return self._projects

    def get_retention_storage(self) -> RetentionStorageInterface:
        return self._retention

    def get_budget_storage(self) -> BudgetStorageInterface:
        return self._budgets

    def get_ledger_storage(self) -> LedgerStorageInterface:
        return self._ledger

    def get_account_storage(self) -> AccountStorageInterface:
        return self._accounts

    def get_money_ledger_storage(self) -> MoneyLedgerStorageInterface:
        return self._money_ledger

    def get_fill_set_storage(self) -> FillSetStorageInterface:
        return self._fill_sets

    def get_window_storage(self) -> WindowStorageInterface:
        return self._windows

    def get_tool_storage(self) -> ToolStorageInterface:
        return self._tools

    def get_evidence_storage(self) -> EvidenceStorageInterface:
        return self._evidence

    def get_placement_storage(self) -> PlacementStorageInterface:
        return self._placement

    def get_trust_storage(self) -> TrustStorageInterface:
        return self._trust

    def get_hosts_storage(self) -> HostsStorageInterface:
        return self._hosts

    def get_intake_storage(self) -> IntakeStorageInterface:
        return self._intake

    def get_automation_storage(self) -> AutomationStorageInterface:
        return self._automation

    def get_playbook_storage(self) -> PlaybookStorageInterface:
        return self._playbook

    def get_knowledge_storage(self) -> KnowledgeStorageInterface:
        return self._knowledge

    def get_notification_storage(self) -> NotificationStorageInterface:
        return self._notification

    def get_platform_agents_storage(self) -> PlatformAgentsStorageInterface:
        return self._platform_agents

    def get_benchmark_storage(self) -> BenchmarkStorageInterface:
        return self._benchmarks

    def get_relay_storage(self) -> RelayStorageInterface:
        return self._relay

    def get_workspace_storage(self) -> WorkspaceStorageInterface:
        return self._workspaces

    def get_matrix_storage(self) -> MatrixStorageInterface:
        return self._matrix

    def get_matrix_tenant_storage(self) -> MatrixTenantStorageInterface:
        return self._matrix_tenants

    async def healthcheck(self) -> bool:
        return True

    async def close(self) -> None:
        return None
