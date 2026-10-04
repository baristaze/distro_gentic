"""Resolves the one container, and the services it holds, for a request or a
socket. Routers name the service they need and make one call into it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from acme.services.api.services import (
    AdminServiceInterface,
    AgentSessionsServiceInterface,
    AutomationsServiceInterface,
    BenchmarksServiceInterface,
    BudgetsServiceInterface,
    EventsServiceInterface,
    EvidenceServiceInterface,
    FleetServiceInterface,
    HostsServiceInterface,
    IntakeServiceInterface,
    KnowledgeServiceInterface,
    LedgersServiceInterface,
    MatrixServiceInterface,
    MediaServiceInterface,
    NotificationsServiceInterface,
    PlaybooksServiceInterface,
    ProjectsServiceInterface,
    ProviderKeysServiceInterface,
    RealtimeServiceInterface,
    RelayServiceInterface,
    RetentionServiceInterface,
    ServicesInterface,
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


def automations_service(connection: HTTPConnection) -> AutomationsServiceInterface:
    return services_of(connection).get_automations_service()


def budgets_service(connection: HTTPConnection) -> BudgetsServiceInterface:
    return services_of(connection).get_budgets_service()


def intake_service(connection: HTTPConnection) -> IntakeServiceInterface:
    return services_of(connection).get_intake_service()


def notifications_service(connection: HTTPConnection) -> NotificationsServiceInterface:
    return services_of(connection).get_notifications_service()


def matrix_service(connection: HTTPConnection) -> MatrixServiceInterface:
    return services_of(connection).get_matrix_service()


def provider_keys_service(connection: HTTPConnection) -> ProviderKeysServiceInterface:
    return services_of(connection).get_provider_keys_service()


def benchmarks_service(connection: HTTPConnection) -> BenchmarksServiceInterface:
    return services_of(connection).get_benchmarks_service()


def ledgers_service(connection: HTTPConnection) -> LedgersServiceInterface:
    return services_of(connection).get_ledgers_service()


def projects_service(connection: HTTPConnection) -> ProjectsServiceInterface:
    return services_of(connection).get_projects_service()


def knowledge_service(connection: HTTPConnection) -> KnowledgeServiceInterface:
    return services_of(connection).get_knowledge_service()


def playbooks_service(connection: HTTPConnection) -> PlaybooksServiceInterface:
    return services_of(connection).get_playbooks_service()


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
RealtimeService = Annotated[RealtimeServiceInterface, Depends(realtime_service)]
WebhooksService = Annotated[WebhooksServiceInterface, Depends(webhooks_service)]
AgentSessionsService = Annotated[AgentSessionsServiceInterface, Depends(agent_sessions_service)]
EvidenceService = Annotated[EvidenceServiceInterface, Depends(evidence_service)]
HostsService = Annotated[HostsServiceInterface, Depends(hosts_service)]
FleetService = Annotated[FleetServiceInterface, Depends(fleet_service)]
RelayService = Annotated[RelayServiceInterface, Depends(relay_service)]
WatchService = Annotated[WatchServiceInterface, Depends(watch_service)]
AutomationsService = Annotated[AutomationsServiceInterface, Depends(automations_service)]
BudgetsService = Annotated[BudgetsServiceInterface, Depends(budgets_service)]
IntakeService = Annotated[IntakeServiceInterface, Depends(intake_service)]
NotificationsService = Annotated[NotificationsServiceInterface, Depends(notifications_service)]
MatrixService = Annotated[MatrixServiceInterface, Depends(matrix_service)]
ProviderKeysService = Annotated[ProviderKeysServiceInterface, Depends(provider_keys_service)]
BenchmarksService = Annotated[BenchmarksServiceInterface, Depends(benchmarks_service)]
LedgersService = Annotated[LedgersServiceInterface, Depends(ledgers_service)]
ProjectsService = Annotated[ProjectsServiceInterface, Depends(projects_service)]
KnowledgeService = Annotated[KnowledgeServiceInterface, Depends(knowledge_service)]
PlaybooksService = Annotated[PlaybooksServiceInterface, Depends(playbooks_service)]
ToolsService = Annotated[ToolsServiceInterface, Depends(tools_service)]
RetentionService = Annotated[RetentionServiceInterface, Depends(retention_service)]
ValidationsService = Annotated[ValidationsServiceInterface, Depends(validations_service)]
