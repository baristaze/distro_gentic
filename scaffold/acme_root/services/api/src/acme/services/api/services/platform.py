"""The platform's services beside the engine's: one getter per namespace
the platform adds, and a product's service by its namespace's name. A
platform router resolves its service through
`acme.services.api.gateway.platform_resolve`."""

from abc import abstractmethod

from acme.services.api.services import ServicesInterface
from acme.services.api.services.agent_automations import AgentAutomationsServiceInterface
from acme.services.api.services.agent_billing import AgentBillingServiceInterface
from acme.services.api.services.agent_fleet import AgentFleetServiceInterface
from acme.services.api.services.agent_knowledge import AgentKnowledgeServiceInterface
from acme.services.api.services.agent_playbooks import AgentPlaybooksServiceInterface
from acme.services.api.services.agent_projects import AgentProjectsServiceInterface
from acme.services.api.services.benchmarks import BenchmarksServiceInterface
from acme.services.api.services.budgets import BudgetsServiceInterface
from acme.services.api.services.connectors import ConnectorsServiceInterface
from acme.services.api.services.evidence import EvidenceServiceInterface
from acme.services.api.services.exec_relay import ExecRelayServiceInterface
from acme.services.api.services.hosts import HostsServiceInterface
from acme.services.api.services.intake import IntakeServiceInterface
from acme.services.api.services.matrix import MatrixServiceInterface
from acme.services.api.services.park_alerts import ParkAlertsServiceInterface
from acme.services.api.services.provider_keys import ProviderKeysServiceInterface
from acme.services.api.services.retention import RetentionServiceInterface
from acme.services.api.services.spend_ledgers import SpendLedgersServiceInterface
from acme.services.api.services.tools import ToolsServiceInterface
from acme.services.api.services.validations import ValidationsServiceInterface
from acme.services.api.services.watch import WatchServiceInterface


class PlatformServicesInterface(ServicesInterface):
    @abstractmethod
    def get_hosts_service(self) -> HostsServiceInterface: ...

    @abstractmethod
    def get_agent_fleet_service(self) -> AgentFleetServiceInterface: ...

    @abstractmethod
    def get_exec_relay_service(self) -> ExecRelayServiceInterface: ...

    @abstractmethod
    def get_agent_automations_service(self) -> AgentAutomationsServiceInterface: ...

    @abstractmethod
    def get_budgets_service(self) -> BudgetsServiceInterface: ...

    @abstractmethod
    def get_agent_billing_service(self) -> AgentBillingServiceInterface: ...

    @abstractmethod
    def get_intake_service(self) -> IntakeServiceInterface: ...

    @abstractmethod
    def get_park_alerts_service(self) -> ParkAlertsServiceInterface: ...

    @abstractmethod
    def get_watch_service(self) -> WatchServiceInterface: ...

    @abstractmethod
    def get_matrix_service(self) -> MatrixServiceInterface: ...

    @abstractmethod
    def get_provider_keys_service(self) -> ProviderKeysServiceInterface: ...

    @abstractmethod
    def get_benchmarks_service(self) -> BenchmarksServiceInterface: ...

    @abstractmethod
    def get_spend_ledgers_service(self) -> SpendLedgersServiceInterface: ...

    @abstractmethod
    def get_evidence_service(self) -> EvidenceServiceInterface: ...

    @abstractmethod
    def get_agent_projects_service(self) -> AgentProjectsServiceInterface: ...

    @abstractmethod
    def get_agent_knowledge_service(self) -> AgentKnowledgeServiceInterface: ...

    @abstractmethod
    def get_connectors_service(self) -> ConnectorsServiceInterface: ...

    @abstractmethod
    def get_agent_playbooks_service(self) -> AgentPlaybooksServiceInterface: ...

    @abstractmethod
    def get_tools_service(self) -> ToolsServiceInterface: ...

    @abstractmethod
    def get_retention_service(self) -> RetentionServiceInterface: ...

    @abstractmethod
    def get_validations_service(self) -> ValidationsServiceInterface: ...

    @abstractmethod
    def get_product_service(self, namespace: str) -> object:
        """The service of the product's namespace of that name
        (`acme.services.api.product_api`); a name the product declares no
        namespace for is refused (`LookupError`)."""
        ...
