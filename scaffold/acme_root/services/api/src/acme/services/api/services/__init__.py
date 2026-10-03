"""The network-layer root: one getter per service. A router resolves the
service it needs from this object and makes one call into it; the impl
translates the request, calls one manager, and projects the result."""

from abc import ABC, abstractmethod

from acme.services.api.services.admin import AdminServiceInterface
from acme.services.api.services.agent_sessions import AgentSessionsServiceInterface
from acme.services.api.services.automations import AutomationsServiceInterface
from acme.services.api.services.benchmarks import BenchmarksServiceInterface
from acme.services.api.services.budgets import BudgetsServiceInterface
from acme.services.api.services.events import EventsServiceInterface
from acme.services.api.services.fleet import FleetServiceInterface
from acme.services.api.services.hosts import HostsServiceInterface
from acme.services.api.services.intake import IntakeServiceInterface
from acme.services.api.services.ledgers import LedgersServiceInterface
from acme.services.api.services.matrix import MatrixServiceInterface
from acme.services.api.services.media import MediaServiceInterface
from acme.services.api.services.notifications import NotificationsServiceInterface
from acme.services.api.services.provider_keys import ProviderKeysServiceInterface
from acme.services.api.services.realtime import RealtimeServiceInterface
from acme.services.api.services.relay import RelayServiceInterface
from acme.services.api.services.tenancy import TenancyServiceInterface
from acme.services.api.services.watch import WatchServiceInterface
from acme.services.api.services.webhooks import WebhooksServiceInterface

__all__ = [
    "AdminServiceInterface",
    "AgentSessionsServiceInterface",
    "AutomationsServiceInterface",
    "BenchmarksServiceInterface",
    "BudgetsServiceInterface",
    "EventsServiceInterface",
    "FleetServiceInterface",
    "HostsServiceInterface",
    "IntakeServiceInterface",
    "LedgersServiceInterface",
    "MatrixServiceInterface",
    "MediaServiceInterface",
    "NotificationsServiceInterface",
    "ProviderKeysServiceInterface",
    "RealtimeServiceInterface",
    "RelayServiceInterface",
    "ServicesInterface",
    "TenancyServiceInterface",
    "WatchServiceInterface",
    "WebhooksServiceInterface",
]


class ServicesInterface(ABC):
    @abstractmethod
    def get_tenancy_service(self) -> TenancyServiceInterface: ...

    @abstractmethod
    def get_admin_service(self) -> AdminServiceInterface: ...

    @abstractmethod
    def get_events_service(self) -> EventsServiceInterface: ...

    @abstractmethod
    def get_media_service(self) -> MediaServiceInterface: ...

    @abstractmethod
    def get_realtime_service(self) -> RealtimeServiceInterface: ...

    @abstractmethod
    def get_webhooks_service(self) -> WebhooksServiceInterface: ...

    @abstractmethod
    def get_agent_sessions_service(self) -> AgentSessionsServiceInterface: ...

    @abstractmethod
    def get_hosts_service(self) -> HostsServiceInterface: ...

    @abstractmethod
    def get_fleet_service(self) -> FleetServiceInterface: ...

    @abstractmethod
    def get_relay_service(self) -> RelayServiceInterface: ...

    @abstractmethod
    def get_automations_service(self) -> AutomationsServiceInterface: ...

    @abstractmethod
    def get_budgets_service(self) -> BudgetsServiceInterface: ...

    @abstractmethod
    def get_intake_service(self) -> IntakeServiceInterface: ...

    @abstractmethod
    def get_notifications_service(self) -> NotificationsServiceInterface: ...

    @abstractmethod
    def get_watch_service(self) -> WatchServiceInterface: ...

    @abstractmethod
    def get_matrix_service(self) -> MatrixServiceInterface: ...

    @abstractmethod
    def get_provider_keys_service(self) -> ProviderKeysServiceInterface: ...

    @abstractmethod
    def get_benchmarks_service(self) -> BenchmarksServiceInterface: ...

    @abstractmethod
    def get_ledgers_service(self) -> LedgersServiceInterface: ...
