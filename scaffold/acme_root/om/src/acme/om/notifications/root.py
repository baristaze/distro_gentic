"""The notifications swimlane over the engine's managers, as a root builds it.

    notifications = build_notifications(storage, managers, integrations, intake)

The process whose runs park, the session runner, tells after each run;
the maintenance worker holds it for its purge."""

from collections.abc import Callable
from datetime import datetime

from acme.integrations.root import IntegrationsInterface
from acme.om.base import utcnow
from acme.om.intake import IntakeManagerInterface
from acme.om.notifications.impl.manager import NotificationsManagerImpl, NotificationsOptions
from acme.om.notifications.manager import NotificationsManagerInterface
from acme.om.root import Managers
from acme.om.storage.root import StorageInterface


def build_notifications(
    storage: StorageInterface,
    managers: Managers,
    integrations: IntegrationsInterface,
    intake: IntakeManagerInterface,
    *,
    options: NotificationsOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> NotificationsManagerInterface:
    return NotificationsManagerImpl(
        storage.get_notification_storage(),
        managers.agent_sessions,
        managers.steps,
        managers.tools,
        managers.tenancy,
        intake,
        integrations.get_integration,
        options or NotificationsOptions(),
        clock,
    )
