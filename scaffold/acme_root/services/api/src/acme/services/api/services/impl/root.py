"""Composes one service impl per hosted namespace over the managers and
hands back the network-layer root the container holds."""

from datetime import timedelta

from acme.infra.root import InfraInterface
from acme.integrations.root import IntegrationsInterface
from acme.om.automations import AutomationsManagerInterface
from acme.om.intake import IntakeManagerInterface
from acme.om.notifications import NotificationsManagerInterface
from acme.om.root import Managers
from acme.om.trust import TrustOperatorManagerInterface
from acme.services.api.services import (
    AdminServiceInterface,
    AgentSessionsServiceInterface,
    EventsServiceInterface,
    FleetServiceInterface,
    HostsServiceInterface,
    MediaServiceInterface,
    RealtimeServiceInterface,
    RelayServiceInterface,
    ServicesInterface,
    StationsServiceInterface,
    TenancyServiceInterface,
    WebhooksServiceInterface,
)
from acme.services.api.services.automations import AutomationsServiceInterface
from acme.services.api.services.budgets import BudgetsServiceInterface
from acme.services.api.services.impl.admin import AdminServiceImpl
from acme.services.api.services.impl.agent_sessions import AgentSessionsServiceImpl
from acme.services.api.services.impl.automations import AutomationsServiceImpl
from acme.services.api.services.impl.budgets import BudgetsServiceImpl
from acme.services.api.services.impl.events import EventsServiceImpl
from acme.services.api.services.impl.fleet import FleetServiceImpl
from acme.services.api.services.impl.hosts import HostsServiceImpl
from acme.services.api.services.impl.intake import IntakeServiceImpl
from acme.services.api.services.impl.media import MediaServiceImpl
from acme.services.api.services.impl.notifications import NotificationsServiceImpl
from acme.services.api.services.impl.realtime import RealtimeServiceImpl
from acme.services.api.services.impl.relay import RelayServiceImpl
from acme.services.api.services.impl.stations import StationsServiceImpl
from acme.services.api.services.impl.tenancy import TenancyServiceImpl
from acme.services.api.services.impl.webhooks import WebhooksServiceImpl
from acme.services.api.services.intake import IntakeServiceInterface
from acme.services.api.services.notifications import NotificationsServiceInterface


class ServicesImpl(ServicesInterface):
    def __init__(
        self,
        tenancy: TenancyServiceInterface,
        admin: AdminServiceInterface,
        events: EventsServiceInterface,
        media: MediaServiceInterface,
        realtime: RealtimeServiceInterface,
        webhooks: WebhooksServiceInterface,
        agent_sessions: AgentSessionsServiceInterface,
        hosts: HostsServiceInterface,
        fleet: FleetServiceInterface,
        relay: RelayServiceInterface,
        stations: StationsServiceInterface,
        intake: IntakeServiceInterface,
        budgets: BudgetsServiceInterface,
        automations: AutomationsServiceInterface,
        notifications: NotificationsServiceInterface,
    ) -> None:
        self._tenancy = tenancy
        self._admin = admin
        self._events = events
        self._media = media
        self._realtime = realtime
        self._webhooks = webhooks
        self._agent_sessions = agent_sessions
        self._hosts = hosts
        self._fleet = fleet
        self._relay = relay
        self._stations = stations
        self._intake = intake
        self._budgets = budgets
        self._automations = automations
        self._notifications = notifications

    def get_tenancy_service(self) -> TenancyServiceInterface:
        return self._tenancy

    def get_admin_service(self) -> AdminServiceInterface:
        return self._admin

    def get_events_service(self) -> EventsServiceInterface:
        return self._events

    def get_media_service(self) -> MediaServiceInterface:
        return self._media

    def get_realtime_service(self) -> RealtimeServiceInterface:
        return self._realtime

    def get_webhooks_service(self) -> WebhooksServiceInterface:
        return self._webhooks

    def get_agent_sessions_service(self) -> AgentSessionsServiceInterface:
        return self._agent_sessions

    def get_hosts_service(self) -> HostsServiceInterface:
        return self._hosts

    def get_fleet_service(self) -> FleetServiceInterface:
        return self._fleet

    def get_relay_service(self) -> RelayServiceInterface:
        return self._relay

    def get_stations_service(self) -> StationsServiceInterface:
        return self._stations

    def get_intake_service(self) -> IntakeServiceInterface:
        return self._intake

    def get_budgets_service(self) -> BudgetsServiceInterface:
        return self._budgets

    def get_automations_service(self) -> AutomationsServiceInterface:
        return self._automations

    def get_notifications_service(self) -> NotificationsServiceInterface:
        return self._notifications


def build_services(
    managers: Managers,
    infra: InfraInterface,
    integrations: IntegrationsInterface,
    head_max_age: timedelta,
    trust_operator: TrustOperatorManagerInterface,
    *,
    intake: IntakeManagerInterface,
    automations: AutomationsManagerInterface,
    notifications: NotificationsManagerInterface,
) -> ServicesInterface:
    """In-process impls only: a Python caller outside the process reaches the
    same services through the typed client under `clients/python`."""
    return ServicesImpl(
        tenancy=TenancyServiceImpl(managers.tenancy),
        admin=AdminServiceImpl(managers.tenancy_operator, managers.work_operator),
        events=EventsServiceImpl(managers.events),
        media=MediaServiceImpl(managers.media),
        realtime=RealtimeServiceImpl(
            managers.tenancy, managers.events, infra.get_topics(), head_max_age
        ),
        webhooks=WebhooksServiceImpl(
            integrations.get_identity_provider(),
            infra.get_queues(),
            integrations.get_integration,
            intake,
        ),
        agent_sessions=AgentSessionsServiceImpl(
            managers.agent_sessions, managers.agents, managers.steps, managers.tools
        ),
        hosts=HostsServiceImpl(managers.hosts),
        fleet=FleetServiceImpl(managers.placement_operator, trust_operator),
        relay=RelayServiceImpl(managers.relay, infra.get_topics()),
        stations=StationsServiceImpl(managers.stations),
        intake=IntakeServiceImpl(intake),
        budgets=BudgetsServiceImpl(managers.budgets),
        automations=AutomationsServiceImpl(automations),
        notifications=NotificationsServiceImpl(notifications),
    )
