"""The intake swimlane over the engine's managers, as a root builds it.

    intake = build_intake(storage, managers)

`principal_context` is the transition that gives a mapped user's live
context; None takes the tenancy manager's members, as the engine's own
root does. `integrations` is the root whose integrations check an installation's
grant; None holds none, so every connection is unavailable."""

from collections.abc import Callable
from datetime import datetime

from acme.integrations.events import IntegrationAbsentImpl
from acme.integrations.root import IntegrationsInterface
from acme.om.attribution import PrincipalContext
from acme.om.attribution.impl.manager import members_context
from acme.om.base import utcnow
from acme.om.intake.impl.manager import IntakeManagerImpl, IntakeOptions
from acme.om.intake.manager import IntakeManagerInterface
from acme.om.root import Managers
from acme.om.storage.root import StorageInterface


def build_intake(
    storage: StorageInterface,
    managers: Managers,
    *,
    principal_context: PrincipalContext | None = None,
    integrations: IntegrationsInterface | None = None,
    options: IntakeOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> IntakeManagerInterface:
    return IntakeManagerImpl(
        storage.get_intake_storage(),
        managers.agent_sessions,
        managers.agents,
        managers.loop,
        managers.tools,
        managers.events,
        managers.tenancy,
        principal_context or members_context(managers.tenancy),
        IntegrationAbsentImpl if integrations is None else integrations.get_integration,
        options or IntakeOptions(),
        clock,
    )
