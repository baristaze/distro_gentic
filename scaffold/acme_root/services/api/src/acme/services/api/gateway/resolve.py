"""Resolves the one container, and the services it holds, for a request or a
socket. Routers name the service they need and make one call into it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from acme.services.api.services import (
    AdminServiceInterface,
    AgentAutomationsServiceInterface,
    AgentBillingServiceInterface,
    AgentKnowledgeServiceInterface,
    AgentPlaybooksServiceInterface,
    AgentSessionsServiceInterface,
    BenchmarksServiceInterface,
    BudgetsServiceInterface,
    ConnectorsServiceInterface,
    EventsServiceInterface,
    EvidenceServiceInterface,
    FlagsServiceInterface,
    FleetServiceInterface,
    HostsServiceInterface,
    IntakeServiceInterface,
    LeasesServiceInterface,
    MatrixServiceInterface,
    MediaServiceInterface,
    ParkAlertsServiceInterface,
    ProjectsServiceInterface,
    ProviderKeysServiceInterface,
    RealtimeServiceInterface,
    RelayServiceInterface,
    RetentionServiceInterface,
    ServicesInterface,
    SpendLedgersServiceInterface,
    TenancyServiceInterface,
    ToolsServiceInterface,
    ValidationsServiceInterface,
    WatchServiceInterface,
    WebhooksServiceInterface,
)

if TYPE_CHECKING:
    from acme.services.api.container import AppContainer


def container_of(connection: HTTPConnection) -> AppContainer:
    return connection.app.state.container


def services_of(connection: HTTPConnection) -> ServicesInterface:
    return container_of(connection).services


def tenancy_service(connection: HTTPConnection) -> TenancyServiceInterface:
    return services_of(connection).get_tenancy_service()


def admin_service(connection: HTTPConnection) -> AdminServiceInterface:
    return services_of(connection).get_admin_service()


def fleet_service(connection: HTTPConnection) -> FleetServiceInterface:
    return services_of(connection).get_fleet_service()


def events_service(connection: HTTPConnection) -> EventsServiceInterface:
    return services_of(connection).get_events_service()


def webhooks_service(connection: HTTPConnection) -> WebhooksServiceInterface:
    return services_of(connection).get_webhooks_service()


def media_service(connection: HTTPConnection) -> MediaServiceInterface:
    return services_of(connection).get_media_service()


def flags_service(connection: HTTPConnection) -> FlagsServiceInterface:
    return services_of(connection).get_flags_service()


def lease_service(connection: HTTPConnection) -> LeasesServiceInterface:
    return services_of(connection).get_lease_service()


def realtime_service(connection: HTTPConnection) -> RealtimeServiceInterface:
    return services_of(connection).get_realtime_service()


def agent_sessions_service(connection: HTTPConnection) -> AgentSessionsServiceInterface:
    return services_of(connection).get_agent_sessions_service()


def evidence_service(connection: HTTPConnection) -> EvidenceServiceInterface:
    return services_of(connection).get_evidence_service()


def hosts_service(connection: HTTPConnection) -> HostsServiceInterface:
    return services_of(connection).get_hosts_service()


def relay_service(connection: HTTPConnection) -> RelayServiceInterface:
    return services_of(connection).get_relay_service()


def watch_service(connection: HTTPConnection) -> WatchServiceInterface:
    return services_of(connection).get_watch_service()


def agent_automations_service(connection: HTTPConnection) -> AgentAutomationsServiceInterface:
    return services_of(connection).get_agent_automations_service()


def budgets_service(connection: HTTPConnection) -> BudgetsServiceInterface:
    return services_of(connection).get_budgets_service()


def agent_billing_service(connection: HTTPConnection) -> AgentBillingServiceInterface:
    return services_of(connection).get_agent_billing_service()


def intake_service(connection: HTTPConnection) -> IntakeServiceInterface:
    return services_of(connection).get_intake_service()


def park_alerts_service(connection: HTTPConnection) -> ParkAlertsServiceInterface:
    return services_of(connection).get_park_alerts_service()


def matrix_service(connection: HTTPConnection) -> MatrixServiceInterface:
    return services_of(connection).get_matrix_service()


def provider_keys_service(connection: HTTPConnection) -> ProviderKeysServiceInterface:
    return services_of(connection).get_provider_keys_service()


def benchmarks_service(connection: HTTPConnection) -> BenchmarksServiceInterface:
    return services_of(connection).get_benchmarks_service()


def spend_ledgers_service(connection: HTTPConnection) -> SpendLedgersServiceInterface:
    return services_of(connection).get_spend_ledgers_service()


def projects_service(connection: HTTPConnection) -> ProjectsServiceInterface:
    return services_of(connection).get_projects_service()


def agent_knowledge_service(connection: HTTPConnection) -> AgentKnowledgeServiceInterface:
    return services_of(connection).get_agent_knowledge_service()


def connectors_service(connection: HTTPConnection) -> ConnectorsServiceInterface:
    return services_of(connection).get_connectors_service()


def agent_playbooks_service(connection: HTTPConnection) -> AgentPlaybooksServiceInterface:
    return services_of(connection).get_agent_playbooks_service()


def tools_service(connection: HTTPConnection) -> ToolsServiceInterface:
    return services_of(connection).get_tools_service()


def retention_service(connection: HTTPConnection) -> RetentionServiceInterface:
    return services_of(connection).get_retention_service()


def validations_service(connection: HTTPConnection) -> ValidationsServiceInterface:
    return services_of(connection).get_validations_service()


TenancyService = Annotated[TenancyServiceInterface, Depends(tenancy_service)]
AdminService = Annotated[AdminServiceInterface, Depends(admin_service)]
EventsService = Annotated[EventsServiceInterface, Depends(events_service)]
MediaService = Annotated[MediaServiceInterface, Depends(media_service)]
FlagsService = Annotated[FlagsServiceInterface, Depends(flags_service)]
LeasesService = Annotated[LeasesServiceInterface, Depends(lease_service)]
RealtimeService = Annotated[RealtimeServiceInterface, Depends(realtime_service)]
WebhooksService = Annotated[WebhooksServiceInterface, Depends(webhooks_service)]
AgentSessionsService = Annotated[AgentSessionsServiceInterface, Depends(agent_sessions_service)]
EvidenceService = Annotated[EvidenceServiceInterface, Depends(evidence_service)]
HostsService = Annotated[HostsServiceInterface, Depends(hosts_service)]
FleetService = Annotated[FleetServiceInterface, Depends(fleet_service)]
RelayService = Annotated[RelayServiceInterface, Depends(relay_service)]
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
ProjectsService = Annotated[ProjectsServiceInterface, Depends(projects_service)]
AgentKnowledgeService = Annotated[AgentKnowledgeServiceInterface, Depends(agent_knowledge_service)]
ConnectorsService = Annotated[ConnectorsServiceInterface, Depends(connectors_service)]
AgentPlaybooksService = Annotated[AgentPlaybooksServiceInterface, Depends(agent_playbooks_service)]
ToolsService = Annotated[ToolsServiceInterface, Depends(tools_service)]
RetentionService = Annotated[RetentionServiceInterface, Depends(retention_service)]
ValidationsService = Annotated[ValidationsServiceInterface, Depends(validations_service)]
