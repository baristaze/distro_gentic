"""The automations swimlane over the engine's managers, as a root builds it.

    automations = build_automations(
        storage, managers, project_required=True, actions=PRODUCT_KINDS.actions
    )

`project_required` refuses a start that names no project, when it is
saved and when it fires: every stack but a local one sets it, so a
session an automation starts is held by its project's budget and
policies. `actions` are the product's own kinds of action
(`ProductKinds.actions`): every process that writes or fires an
automation hands it the same, and a kind named as one of the platform's,
or twice, is refused here, at boot.

`principal_context` is the transition that gives an automation's creator
their live context at each firing; None takes the tenancy manager's
members, as the engine's own root does. Either way the tenant's automation
principal is answered for by its grant (`automation_principals`), and a
root that runs the sessions an automation starts hands the same transition
to `build_managers`, so their calls run on the principal's role alone."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.attribution import PrincipalContext
from acme.om.attribution.impl.manager import members_context
from acme.om.attribution.types.principal import Principal
from acme.om.automations.actions import AutomationActions
from acme.om.automations.impl.manager import AutomationsManagerImpl, AutomationsOptions
from acme.om.automations.manager import AutomationsManagerInterface
from acme.om.automations.storage import AutomationStorageInterface
from acme.om.base import utcnow
from acme.om.context import CredentialKind, RequestContext, TenantContext, build_context
from acme.om.root import Managers, ProductActions, no_actions
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.rules import permissions_of


def automation_principals(
    storage: AutomationStorageInterface, fallback: PrincipalContext
) -> PrincipalContext:
    """The transition that answers for the tenant's automation principal by
    its grant, read at each call: its id, the role granted, that role's
    permissions, and nothing else, whichever kind a step names it as. Every
    other principal is `fallback`'s to answer."""

    async def live(rctx: RequestContext, org_id: UUID, principal: Principal) -> TenantContext:
        granted = await storage.read_principal(org_id)
        if granted is None or principal.id != granted.id:
            return await fallback(rctx, org_id, principal)
        return build_context(
            rctx,
            user_id=granted.id,
            org_id=org_id,
            role=granted.role,
            permissions=permissions_of(granted.role),
            credential_kind=CredentialKind.INTERNAL,
        )

    return live


def build_automations(
    storage: StorageInterface,
    managers: Managers,
    *,
    project_required: bool,
    principal_context: PrincipalContext | None = None,
    options: AutomationsOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
    actions: ProductActions = no_actions,
) -> AutomationsManagerInterface:
    held = storage.get_automation_storage()
    return AutomationsManagerImpl(
        held,
        managers.agents,
        managers.agent_sessions,
        managers.budgets,
        managers.tenancy,
        managers.outbox,
        managers.events,
        managers.projects,
        automation_principals(held, principal_context or members_context(managers.tenancy)),
        options or AutomationsOptions(),
        clock,
        project_required=project_required,
        actions=AutomationActions(actions(lambda: managers)),
    )
