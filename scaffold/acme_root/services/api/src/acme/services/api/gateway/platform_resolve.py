"""Resolves the platform's services, and a product's, for a request or a
socket, as `resolve` does the engine's. A platform router names the service
it needs from here; a product's router names its own through
`product_service`."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from acme.services.api.gateway.resolve import container_of
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
from acme.services.api.services.platform import PlatformServicesInterface
from acme.services.api.services.provider_keys import ProviderKeysServiceInterface
from acme.services.api.services.retention import RetentionServiceInterface
from acme.services.api.services.spend_ledgers import SpendLedgersServiceInterface
from acme.services.api.services.tools import ToolsServiceInterface
from acme.services.api.services.validations import ValidationsServiceInterface
from acme.services.api.services.watch import WatchServiceInterface


def platform_services_of(connection: HTTPConnection) -> PlatformServicesInterface:
    """The container's services, the platform's beside the engine's."""
    return container_of(connection).services


def product_service[S](namespace: str, interface: type[S]) -> Callable[[HTTPConnection], S]:
    """The resolver of a product's namespace's service, as its router names
    it: `Annotated[interface, Depends(product_service(namespace, interface))]`.
    A service that is not an `interface` is refused."""

    def resolve(connection: HTTPConnection) -> S:
        service = platform_services_of(connection).get_product_service(namespace)
        if not isinstance(service, interface):
            raise TypeError(f"the {namespace} service is no {interface.__name__}")
        return service

    return resolve


def agent_fleet_service(connection: HTTPConnection) -> AgentFleetServiceInterface:
    return platform_services_of(connection).get_agent_fleet_service()


def evidence_service(connection: HTTPConnection) -> EvidenceServiceInterface:
    return platform_services_of(connection).get_evidence_service()


def hosts_service(connection: HTTPConnection) -> HostsServiceInterface:
    return platform_services_of(connection).get_hosts_service()


def exec_relay_service(connection: HTTPConnection) -> ExecRelayServiceInterface:
    return platform_services_of(connection).get_exec_relay_service()


def watch_service(connection: HTTPConnection) -> WatchServiceInterface:
    return platform_services_of(connection).get_watch_service()


def agent_automations_service(connection: HTTPConnection) -> AgentAutomationsServiceInterface:
    return platform_services_of(connection).get_agent_automations_service()


def budgets_service(connection: HTTPConnection) -> BudgetsServiceInterface:
    return platform_services_of(connection).get_budgets_service()


def agent_billing_service(connection: HTTPConnection) -> AgentBillingServiceInterface:
    return platform_services_of(connection).get_agent_billing_service()


def intake_service(connection: HTTPConnection) -> IntakeServiceInterface:
    return platform_services_of(connection).get_intake_service()


def park_alerts_service(connection: HTTPConnection) -> ParkAlertsServiceInterface:
    return platform_services_of(connection).get_park_alerts_service()


def matrix_service(connection: HTTPConnection) -> MatrixServiceInterface:
    return platform_services_of(connection).get_matrix_service()


def provider_keys_service(connection: HTTPConnection) -> ProviderKeysServiceInterface:
    return platform_services_of(connection).get_provider_keys_service()


def benchmarks_service(connection: HTTPConnection) -> BenchmarksServiceInterface:
    return platform_services_of(connection).get_benchmarks_service()


def spend_ledgers_service(connection: HTTPConnection) -> SpendLedgersServiceInterface:
    return platform_services_of(connection).get_spend_ledgers_service()


def agent_projects_service(connection: HTTPConnection) -> AgentProjectsServiceInterface:
    return platform_services_of(connection).get_agent_projects_service()


def agent_knowledge_service(connection: HTTPConnection) -> AgentKnowledgeServiceInterface:
    return platform_services_of(connection).get_agent_knowledge_service()


def connectors_service(connection: HTTPConnection) -> ConnectorsServiceInterface:
    return platform_services_of(connection).get_connectors_service()


def agent_playbooks_service(connection: HTTPConnection) -> AgentPlaybooksServiceInterface:
    return platform_services_of(connection).get_agent_playbooks_service()


def tools_service(connection: HTTPConnection) -> ToolsServiceInterface:
    return platform_services_of(connection).get_tools_service()


def retention_service(connection: HTTPConnection) -> RetentionServiceInterface:
    return platform_services_of(connection).get_retention_service()


def validations_service(connection: HTTPConnection) -> ValidationsServiceInterface:
    return platform_services_of(connection).get_validations_service()


EvidenceService = Annotated[EvidenceServiceInterface, Depends(evidence_service)]
HostsService = Annotated[HostsServiceInterface, Depends(hosts_service)]
AgentFleetService = Annotated[AgentFleetServiceInterface, Depends(agent_fleet_service)]
ExecRelayService = Annotated[ExecRelayServiceInterface, Depends(exec_relay_service)]
WatchService = Annotated[WatchServiceInterface, Depends(watch_service)]
AgentAutomationsService = Annotated[
    AgentAutomationsServiceInterface, Depends(agent_automations_service)
]
BudgetsService = Annotated[BudgetsServiceInterface, Depends(budgets_service)]
AgentBillingService = Annotated[AgentBillingServiceInterface, Depends(agent_billing_service)]
IntakeService = Annotated[IntakeServiceInterface, Depends(intake_service)]
ParkAlertsService = Annotated[ParkAlertsServiceInterface, Depends(park_alerts_service)]
MatrixService = Annotated[MatrixServiceInterface, Depends(matrix_service)]
ProviderKeysService = Annotated[ProviderKeysServiceInterface, Depends(provider_keys_service)]
BenchmarksService = Annotated[BenchmarksServiceInterface, Depends(benchmarks_service)]
SpendLedgersService = Annotated[SpendLedgersServiceInterface, Depends(spend_ledgers_service)]
AgentProjectsService = Annotated[AgentProjectsServiceInterface, Depends(agent_projects_service)]
AgentKnowledgeService = Annotated[AgentKnowledgeServiceInterface, Depends(agent_knowledge_service)]
ConnectorsService = Annotated[ConnectorsServiceInterface, Depends(connectors_service)]
AgentPlaybooksService = Annotated[AgentPlaybooksServiceInterface, Depends(agent_playbooks_service)]
ToolsService = Annotated[ToolsServiceInterface, Depends(tools_service)]
RetentionService = Annotated[RetentionServiceInterface, Depends(retention_service)]
ValidationsService = Annotated[ValidationsServiceInterface, Depends(validations_service)]
