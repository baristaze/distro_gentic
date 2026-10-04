"""The platform's loop over the memory storage and the scripted provider,
with the intake, automations, playbooks, knowledge, and notifications
swimlanes wired as a root wires them, every integration served by its
twin: the engine's tools manager wrapped in the trust layer,
the playbooks layer, and the knowledge layer, and each manager built over
the engine's. What
their suites share: a tenant whose members a case names with a role, the
tenant's service context, and the steps a session holds."""

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from acme.infra.impl.local import InfraLocalImpl
from acme.integrations.events.twin import IntegrationTwinImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import ModelProvidersOverImpl
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om.agents.impl.loop import LoopManagerImpl, LoopOptions
from acme.om.agents.impl.sink import StreamSinkMemoryImpl
from acme.om.agents.types.kind import AgentKindCatalog
from acme.om.agents.types.request import Start
from acme.om.attribution import PrincipalContext
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.automations.manager import AutomationsManagerInterface
from acme.om.automations.root import automation_principals, build_automations
from acme.om.base import EMPTY_UUID, new_id, utcnow
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    RequestContext,
    Role,
    TenantContext,
    build_context,
)
from acme.om.exceptions import NotAuthorized
from acme.om.intake.manager import IntakeManagerInterface
from acme.om.intake.root import build_intake
from acme.om.intake.tools import COMMENT, CommentImpl
from acme.om.knowledge.manager import KnowledgeManagerInterface
from acme.om.knowledge.root import KnowledgeLayer
from acme.om.models.impl.credentials import CallCredentialsPlatformImpl
from acme.om.notifications.manager import NotificationsManagerInterface
from acme.om.notifications.root import build_notifications
from acme.om.playbooks.manager import PlaybooksManagerInterface
from acme.om.playbooks.root import PlaybooksLayer
from acme.om.projects.impl.policies import SessionProjectsBoundImpl
from acme.om.root import Managers, ProductActions, build_managers, engine_tools, no_actions
from acme.om.steps.types.step import Step
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.rules import permissions_of
from acme.om.tenancy.types.identity import Identity
from acme.om.tenancy.types.membership import Membership
from acme.om.tenancy.types.user import User
from acme.om.tools.impl.attachments import AttachmentReaderNullImpl
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.native.ask_person import ASK_PERSON
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.policy import Decision, PolicyLayer, PolicyRule
from acme.om.tools.types.tool import ToolClass
from acme.om.trust.impl.keys import KeyProbeTwinImpl
from acme.om.trust.root import TrustLayer
from acme.om.windows.impl.gate import CallGateBudgetImpl
from contracts.doubles import APP
from contracts.factories import make_org
from contracts.loops import Clock, Lookup
from contracts.tools import INJECTED_TOKEN, Command
from contracts.trust import ALLOWED, STEADY, Placement

WORKER = AppContext(type=AppType.WORKER, version="worker@test")

ACTING = STEADY.model_copy(
    update={
        "name": "acting",
        "tools": (*STEADY.tools, COMMENT),
        "policy": PolicyLayer(
            rules=(
                *ALLOWED.rules,
                PolicyRule(authorization_class=ToolClass.INTEGRATION, decision=Decision.ALLOW),
            )
        ),
    }
)
"""A steady kind that also comments on the forge as the platform's
account."""

ASKING = STEADY.model_copy(update={"name": "asking", "tools": (*STEADY.tools, ASK_PERSON)})
"""A steady kind that also asks its person what it cannot find."""
KINDS = (STEADY, ACTING, ASKING)


@dataclass
class Members:
    """The adopter's transition: each person a case names holds a member's
    place with the role it gives, read live, as an agent's call or an
    automation's firing reads it; anyone else holds none."""

    org_id: UUID
    roles: dict[UUID, Role] = field(default_factory=dict[UUID, Role])

    async def __call__(
        self, rctx: RequestContext, org_id: UUID, principal: Principal
    ) -> TenantContext:
        role = self.roles.get(principal.id)
        if role is None or org_id != self.org_id:
            raise NotAuthorized(f"{principal.id} holds no place in the org")
        return build_context(
            rctx,
            user_id=principal.id,
            org_id=org_id,
            role=role,
            permissions=permissions_of(role),
            credential_kind=CredentialKind.INTERNAL,
        )


@dataclass
class Wired:
    infra: InfraLocalImpl
    managers: Managers
    loops: LoopManagerImpl
    anthropic: ModelProviderScriptedImpl
    clock: Clock
    members: Members
    principals: PrincipalContext
    """The root's transition: the tenant's automation principal by its
    grant, and everyone else as `members` answers."""
    owner: TenantContext
    service: TenantContext
    intake: IntakeManagerInterface
    automations: AutomationsManagerInterface
    playbooks: PlaybooksManagerInterface
    knowledge: KnowledgeManagerInterface
    notifications: NotificationsManagerInterface
    chat: IntegrationTwinImpl
    forge: IntegrationTwinImpl
    storage: StorageInterface
    lookup: Lookup

    def person(self, role: Role = Role.MEMBER) -> TenantContext:
        """A member of the tenant at the portal, in person, with `role`."""
        ctx = build_context(
            RequestContext(request_id=new_id(), app=APP),
            user_id=new_id(),
            org_id=self.owner.org_id,
            role=role,
            permissions=permissions_of(role),
            credential_kind=CredentialKind.SESSION_TOKEN,
        )
        self.members.roles[ctx.user_id] = role
        return ctx

    async def member(self, role: Role = Role.MEMBER) -> TenantContext:
        """A person at the portal, as `person` gives one, whose membership the
        tenant also holds, so a listing of its members finds them."""
        ctx = self.person(role)
        tenancy = self.storage.get_tenancy_storage()
        now = utcnow()
        identity_id = new_id()
        email = f"{ctx.user_id.hex}@example.test"
        await tenancy.write_identity(
            Identity(
                id=identity_id,
                created_at=now,
                updated_at=now,
                created_by=identity_id,
                updated_by=identity_id,
                email=email,
            )
        )
        await tenancy.write_user(
            ctx.org_id,
            User(
                id=ctx.user_id,
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                identity_id=identity_id,
                email=email,
                display_name="A member",
            ),
        )
        await tenancy.write_membership(
            ctx.org_id,
            Membership(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                user_id=ctx.user_id,
                role=role,
            ),
        )
        return ctx

    async def agents_call(self, ctx: TenantContext) -> TenantContext:
        """The context an agent's call runs under on `ctx`'s authority: their
        live place, internal, never in person."""
        principal = Principal(kind=PrincipalKind.PERSON, id=ctx.user_id)
        rctx = RequestContext(request_id=new_id(), app=WORKER)
        return await self.members(rctx, ctx.org_id, principal)

    async def start(self, ctx: TenantContext | None = None) -> UUID:
        session = await self.managers.agents.start_session(
            ctx or self.owner, Start(id=new_id(), kind="steady", title="the records")
        )
        return session.id

    async def history(self, session_id: UUID) -> list[Step]:
        steps: list[Step] = []
        while True:
            after = steps[-1].seq if steps else 0
            page = await self.managers.steps.get_steps(self.owner, session_id, after, 200)
            steps.extend(page.items)
            if not page.has_more or not page.items:
                return steps


def wired(
    tmp_path: Path,
    *,
    storage: StorageInterface | None = None,
    owner: TenantContext | None = None,
    project_required: bool = False,
    actions: ProductActions = no_actions,
) -> Wired:
    """`storage` None is the memory storage, and `owner` None a fresh
    tenant's owner; a suite over Postgres hands in both. `project_required`
    is the automations' as a stack outside `local` sets it, and `actions`
    the product's own kinds of automation action."""
    infra = InfraLocalImpl(tmp_path)
    anthropic = ModelProviderScriptedImpl(ProviderName.ANTHROPIC)
    openai = ModelProviderScriptedImpl(ProviderName.OPENAI)
    providers = ModelProvidersOverImpl(
        {ProviderName.ANTHROPIC: anthropic, ProviderName.OPENAI: openai}
    )
    storage = storage or StorageMemoryImpl()
    owner = owner or build_context(
        RequestContext(request_id=new_id(), app=APP),
        user_id=new_id(),
        org_id=make_org().id,
        role=Role.OWNER,
        permissions=permissions_of(Role.OWNER),
        credential_kind=CredentialKind.SESSION_TOKEN,
    )
    members = Members(org_id=owner.org_id)
    members.roles[owner.user_id] = Role.OWNER
    principals = automation_principals(storage.get_automation_storage(), members)
    service = build_context(
        RequestContext(request_id=new_id(), app=WORKER),
        user_id=EMPTY_UUID,
        org_id=owner.org_id,
        role=Role.SERVICE,
        permissions=permissions_of(Role.SERVICE),
        credential_kind=CredentialKind.INTERNAL,
    )
    lookup = Lookup()
    chat, forge = IntegrationTwinImpl("chat"), IntegrationTwinImpl("forge")
    integrations = IntegrationsOverImpl(
        IdentityProviderAbsentImpl(), providers, {"chat": chat, "forge": forge}
    )
    catalog: tuple[ToolInterface, ...] = (
        lookup,
        Command("call_api", secrets=(INJECTED_TOKEN,)),
        CommentImpl(lambda: intake, integrations.get_integration),
    )
    clock = Clock()
    trust = TrustLayer(
        storage,
        infra,
        placement=Placement(),
        probe=KeyProbeTwinImpl(refused=frozenset()),
        clock=clock,
    )
    playbooks = PlaybooksLayer(storage, clock=clock)
    knowledge = KnowledgeLayer(storage, clock=clock)

    def layers(inner: ToolsManagerInterface) -> ToolsManagerInterface:
        return knowledge.tools(playbooks.tools(trust.tools(inner)))

    managers = build_managers(
        storage,
        infra,
        integrations=integrations,
        agent_kinds=KINDS,
        principal_context=principals,
        tool_catalog=catalog,
        tools_layer=layers,
    )
    trust.build(managers)

    async def sleep(seconds: float) -> None:
        clock.now += timedelta(seconds=seconds)
        await asyncio.sleep(0)

    loops = LoopManagerImpl(
        managers.steps,
        managers.agent_sessions,
        managers.agents,
        AgentKindCatalog(kinds=KINDS),
        managers.attribution,
        managers.models,
        managers.windows,
        managers.tools,
        CallGateBudgetImpl(
            managers.budget_gate,
            managers.pricing,
            managers.agent_sessions,
            managers.budgets,
            SessionProjectsBoundImpl(storage.get_project_storage()),
        ),
        CallCredentialsPlatformImpl(providers),
        infra.get_outages(),
        StreamSinkMemoryImpl(),
        engine_tools(managers.steps, AttachmentReaderNullImpl()) + catalog,
        LoopOptions(control_poll=timedelta(milliseconds=1)),
        clock,
        sleep,
    )
    intake = build_intake(storage, managers, principal_context=members, clock=clock)
    return Wired(
        infra=infra,
        managers=managers,
        loops=loops,
        anthropic=anthropic,
        clock=clock,
        members=members,
        principals=principals,
        owner=owner,
        service=service,
        intake=intake,
        automations=build_automations(
            storage,
            managers,
            project_required=project_required,
            principal_context=members,
            clock=clock,
            actions=actions,
        ),
        playbooks=playbooks.build(managers),
        knowledge=knowledge.build(managers),
        notifications=build_notifications(storage, managers, integrations, intake, clock=clock),
        chat=chat,
        forge=forge,
        storage=storage,
        lookup=lookup,
    )
