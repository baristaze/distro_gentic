"""The agent automations swimlane over the engine's managers, as a root builds it.

    agent_automations = build_agent_automations(
        storage, managers, agent_project_required=True, actions=PRODUCT_KINDS.actions
    )

`agent_project_required` refuses a start that names no agent project, when it is
saved and when it fires: every stack but a local one sets it, so a
session an agent automation starts is held by its agent project's budget and
policies. `actions` are the product's own kinds of action
(`ProductKinds.actions`): every process that writes or fires an
agent automation hands it the same, and a kind named as one of the platform's,
or twice, is refused here, at boot.

`agent_playbooks` answers the agent playbooks a start invokes into the session it
starts: the process's agent playbooks manager, which a root builds after the
managers, so the edge is bound at call time. None keeps none, and a start
that names one is refused.

`principal_context` is the transition that gives an agent automation's creator
their live context at each firing; None takes the tenancy manager's
members, as the engine's own root does. Either way the tenant's agent automation
principal is answered for by its grant (`agent_automation_principals`), and a
root that runs the sessions an agent automation starts hands the same transition
to `build_managers`, so their calls run on the principal's role alone."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.agent_automations.actions import AgentAutomationActions
from acme.om.agent_automations.impl.manager import (
    AgentAutomationsManagerImpl,
    AgentAutomationsOptions,
)
from acme.om.agent_automations.manager import AgentAutomationsManagerInterface
from acme.om.agent_automations.storage import AgentAutomationStorageInterface
from acme.om.agent_playbooks import AgentPlaybooksManagerInterface
from acme.om.attribution import PrincipalContext
from acme.om.attribution.impl.manager import members_context
from acme.om.attribution.types.principal import Principal
from acme.om.base import utcnow
from acme.om.context import CredentialKind, RequestContext, TenantContext, build_context
from acme.om.root import Managers, ProductActions, no_actions
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.rules import permissions_of


def agent_automation_principals(
    storage: AgentAutomationStorageInterface, fallback: PrincipalContext
) -> PrincipalContext:
    """The transition that answers for the tenant's agent automation principal by
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


def build_agent_automations(
    storage: StorageInterface,
    managers: Managers,
    *,
    agent_project_required: bool,
    principal_context: PrincipalContext | None = None,
    options: AgentAutomationsOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
    actions: ProductActions = no_actions,
    agent_playbooks: Callable[[], AgentPlaybooksManagerInterface] | None = None,
) -> AgentAutomationsManagerInterface:
    held = storage.get_agent_automation_storage()
    return AgentAutomationsManagerImpl(
        held,
        managers.agents,
        managers.agent_sessions,
        managers.budgets,
        managers.tenancy,
        managers.outbox,
        managers.events,
        managers.agent_projects,
        agent_automation_principals(held, principal_context or members_context(managers.tenancy)),
        options or AgentAutomationsOptions(),
        clock,
        agent_project_required=agent_project_required,
        actions=AgentAutomationActions(actions(lambda: managers)),
        agent_playbooks=agent_playbooks,
    )
