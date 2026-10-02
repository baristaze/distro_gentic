"""The automations swimlane over the engine's managers, as a root builds it.

    automations = build_automations(storage, managers)

`principal_context` is the transition that gives an automation's creator
their live context at each firing; None takes the tenancy manager's
members, as the engine's own root does."""

from collections.abc import Callable
from datetime import datetime

from acme.om.attribution import PrincipalContext
from acme.om.attribution.impl.manager import members_context
from acme.om.automations.impl.manager import AutomationsManagerImpl, AutomationsOptions
from acme.om.automations.manager import AutomationsManagerInterface
from acme.om.base import utcnow
from acme.om.root import Managers
from acme.om.storage.root import StorageInterface


def build_automations(
    storage: StorageInterface,
    managers: Managers,
    *,
    principal_context: PrincipalContext | None = None,
    options: AutomationsOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> AutomationsManagerInterface:
    return AutomationsManagerImpl(
        storage.get_automation_storage(),
        managers.agents,
        managers.agent_sessions,
        managers.budgets,
        managers.tenancy,
        managers.outbox,
        principal_context or members_context(managers.tenancy),
        options or AutomationsOptions(),
        clock,
    )
