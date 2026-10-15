"""The park alerts swimlane over the engine's managers, as a root builds it.

    park_alerts = build_park_alerts(storage, managers, integrations, intake)

The process whose runs park, the session runner, tells after each run;
the maintenance worker holds it for its purge."""

from collections.abc import Callable
from datetime import datetime

from acme.integrations.root import IntegrationsInterface
from acme.om.base import utcnow
from acme.om.intake import IntakeManagerInterface
from acme.om.park_alerts.impl.manager import ParkAlertsManagerImpl, ParkAlertsOptions
from acme.om.park_alerts.manager import ParkAlertsManagerInterface
from acme.om.platform_root import PlatformManagers
from acme.om.storage.root import StorageInterface


def build_park_alerts(
    storage: StorageInterface,
    managers: PlatformManagers,
    integrations: IntegrationsInterface,
    intake: IntakeManagerInterface,
    *,
    options: ParkAlertsOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> ParkAlertsManagerInterface:
    return ParkAlertsManagerImpl(
        storage.get_park_alert_storage(),
        managers.agent_sessions,
        managers.agent_steps,
        managers.tools,
        managers.tenancy,
        intake,
        integrations.get_integration,
        options or ParkAlertsOptions(),
        clock,
    )
