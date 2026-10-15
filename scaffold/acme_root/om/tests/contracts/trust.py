"""The platform's loop over the memory storage, the scripted provider, and
the twin transport, with the trust swimlane wired as a root wires it: the
engine's tools manager wrapped in the trust layer, and the trust managers
built over the engine's. What the trust suites share: a transition whose
principals a case can revoke, a placement a case can put inside a
customer's wall, and the agent kinds the cases run."""

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.transports.twin import TransportTwinImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import ModelProvidersOverImpl
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om.agent_projects.impl.policies import SessionAgentProjectsBoundImpl
from acme.om.agent_projects.types.agent_project import AgentProject
from acme.om.agent_root import AgentRootOptions
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agents.impl.hooks import LoopHooksNullImpl
from acme.om.agents.impl.loop import LoopManagerImpl, LoopOptions
from acme.om.agents.impl.sink import StreamSinkMemoryImpl
from acme.om.agents.types.kind import AgentKind, AgentKindCatalog, DoneRule, TreeLimits
from acme.om.agents.types.request import Start
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import new_id
from acme.om.context import (
    CredentialKind,
    RequestContext,
    Role,
    TenantContext,
    build_context,
)
from acme.om.exceptions import NotAuthorized
from acme.om.language_models.impl.credentials import CallCredentialsPlatformImpl
from acme.om.platform_root import (
    PlatformManagers,
    PlatformRootOptions,
    ProductKinds,
    build_platform_managers,
)
from acme.om.spend_budgets.types.amount import Amount
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.rules import permissions_of
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.policy import Decision, ToolPolicyLayer, ToolPolicyRule
from acme.om.tools.types.tool import Effect, ToolClass
from acme.om.trust.impl.keys import KeyProbeTwinImpl
from acme.om.trust.impl.manager import TrustOptions
from acme.om.trust.keys import ClientFactory
from acme.om.trust.placement import PlacementInterface
from acme.om.trust.root import TrustLayer, TrustManagers, absent_client
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.windows.impl.gate import CallGateSpendBudgetImpl

from contracts.agent_project_storage import make_agent_project, make_binding
from contracts.agent_step_storage import make_message
from contracts.doubles import APP, context
from contracts.factories import make_org
from contracts.loops import Clock, Lookup
from contracts.tools import INJECTED_TOKEN, TWIN_SPEC, Command

ALLOWED = ToolPolicyLayer(
    rules=(
        ToolPolicyRule(authorization_class=ToolClass.READ, decision=Decision.ALLOW),
        ToolPolicyRule(authorization_class=ToolClass.EXECUTE, decision=Decision.ALLOW),
    )
)

STEADY = AgentKind(
    name="steady",
    version=1,
    tools=("lookup", "call_api"),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=2, count=4),
    share=Amount(tokens=1_000_000),
    prompts=("You keep the records, under the authority of whoever started you.",),
    policy=ALLOWED,
    isolation=TWIN_SPEC,
)
"""A steady kind that answers when it is done: its calls run under the
person who started the session, whoever speaks to it later."""


class Transition:
    """The adopter's transition: every principal holds a member's place in
    the tenant until a case revokes it."""

    def __init__(self) -> None:
        self.revoked: set[UUID] = set()

    async def __call__(
        self, rctx: RequestContext, org_id: UUID, principal: Principal
    ) -> TenantContext:
        if principal.id in self.revoked:
            raise NotAuthorized(f"{principal.id} left the tenant")
        return build_context(
            rctx,
            user_id=principal.id,
            org_id=org_id,
            role=Role.MEMBER,
            permissions=permissions_of(Role.MEMBER),
            credential_kind=CredentialKind.AUTH_SESSION_TOKEN,
        )


@dataclass
class Placement(PlacementInterface):
    """The sessions a case puts inside a customer's wall run on its host;
    every other one runs in the cloud."""

    host: Executor = field(
        default_factory=lambda: Executor(
            kind=ExecutorKind.HOST, credential_id=new_id(), label="build-host-1"
        )
    )
    cloud: Executor = field(
        default_factory=lambda: Executor(
            kind=ExecutorKind.CLOUD, credential_id=new_id(), label="session-runner-1"
        )
    )
    walled: set[UUID] = field(default_factory=set[UUID])

    async def inside_wall(self, org_id: UUID, agent_session_id: UUID) -> bool:
        return agent_session_id in self.walled

    async def executor_of(self, org_id: UUID, agent_session_id: UUID) -> Executor:
        return self.host if agent_session_id in self.walled else self.cloud


@dataclass
class Trusted:
    infra: InfraLocalImpl
    storage: StorageInterface
    managers: PlatformManagers
    trust: TrustManagers
    trust_options: TrustOptions
    loops: LoopManagerImpl
    anthropic: ModelProviderScriptedImpl
    sink: StreamSinkMemoryImpl
    clock: Clock
    owner: TenantContext
    transition: Transition
    placement: Placement
    probe: KeyProbeTwinImpl
    lookup: Lookup
    # The owner's agent project, where a suite's sessions start and its secrets
    # are declared.
    agent_project: AgentProject = field(default_factory=make_agent_project)

    @property
    def transport(self) -> TransportTwinImpl:
        transport = self.infra.get_transport()
        assert isinstance(transport, TransportTwinImpl)
        return transport

    def member(self, role: Role = Role.MEMBER) -> TenantContext:
        """Another person of the owner's tenant, a member unless `role` says
        otherwise."""
        return build_context(
            RequestContext(request_id=new_id(), app=APP),
            user_id=new_id(),
            org_id=self.owner.org_id,
            role=role,
            permissions=permissions_of(role),
            credential_kind=CredentialKind.AUTH_SESSION_TOKEN,
        )

    async def owners_agent_project(self) -> UUID:
        """The owner's agent project, written on its first use."""
        agent_projects = self.storage.get_agent_project_storage()
        await agent_projects.create_agent_project(self.owner.org_id, self.agent_project, ())
        return self.agent_project.id

    async def start(
        self, ctx: TenantContext | None = None, kind: str = "steady", *, agent_project: bool = False
    ) -> UUID:
        """A session of no agent project, or of the owner's. Its agent project's row is
        written once it stands, so no workspace checks the agent project out."""
        session = await self.managers.agents.start_agent_session(
            ctx or self.owner, Start(id=new_id(), kind=kind, title="the records")
        )
        if agent_project:
            binding = make_binding(session.id, await self.owners_agent_project())
            await self.storage.get_agent_project_storage().bind_session(self.owner.org_id, binding)
        return session.id

    async def say(
        self, agent_session_id: UUID, text: str, ctx: TenantContext | None = None
    ) -> AgentStep:
        ctx = ctx or self.owner
        person = Principal(kind=PrincipalKind.PERSON, id=ctx.user_id)
        message = make_message(agent_session_id, text, principal=person)
        (stored,) = await self.managers.agent_steps.append_inputs(ctx, agent_session_id, [message])
        return stored

    async def history(self, agent_session_id: UUID) -> list[AgentStep]:
        steps: list[AgentStep] = []
        while True:
            after = steps[-1].seq if steps else 0
            page = await self.managers.agent_steps.get_agent_steps(
                self.owner, agent_session_id, after, 200
            )
            steps.extend(page.items)
            if not page.has_more or not page.items:
                return steps


def trusted(
    tmp_path: Path,
    *,
    clients: ClientFactory = absent_client,
    storage: StorageInterface | None = None,
    owner: TenantContext | None = None,
    product_kinds: ProductKinds | None = None,
) -> Trusted:
    """`storage` None is the memory storage, and `owner` None a fresh
    tenant's owner; a suite over Postgres hands in both. `product_kinds` is
    what a product registers beside the platform's kinds."""
    infra = InfraLocalImpl(tmp_path)
    anthropic = ModelProviderScriptedImpl(ProviderName.ANTHROPIC)
    openai = ModelProviderScriptedImpl(ProviderName.OPENAI)
    providers = ModelProvidersOverImpl(
        {ProviderName.ANTHROPIC: anthropic, ProviderName.OPENAI: openai}
    )
    storage = storage or StorageMemoryImpl()
    transition = Transition()
    placement = Placement()
    probe = KeyProbeTwinImpl(refused=frozenset({"sk-refused"}))
    lookup = Lookup()
    catalog: tuple[ToolInterface, ...] = (
        lookup,
        Command("call_api", effect=Effect.IDEMPOTENT, secrets=(INJECTED_TOKEN,)),
    )
    clock = Clock()
    layer = TrustLayer(
        storage,
        infra,
        placement=placement,
        probe=probe,
        clients=clients,
        product_kinds=product_kinds,
        clock=clock,
    )
    managers = build_platform_managers(
        storage,
        infra,
        integrations=IntegrationsOverImpl(IdentityProviderAbsentImpl(), providers),
        platform_root_options=PlatformRootOptions(
            tools_layer=layer.tools,
            product_kinds=product_kinds,
        ),
        agent_root_options=AgentRootOptions(
            agent_kinds=(STEADY,), principal_context=transition, tool_catalog=catalog
        ),
    )
    trust = layer.build(managers)

    async def sleep(seconds: float) -> None:
        clock.now += timedelta(seconds=seconds)
        await asyncio.sleep(0)

    sink = StreamSinkMemoryImpl()
    loops = LoopManagerImpl(
        managers.agent_steps,
        managers.agent_sessions,
        managers.agents,
        AgentKindCatalog(kinds=(STEADY,)),
        managers.attribution,
        managers.language_models,
        managers.windows,
        managers.tools,
        CallGateSpendBudgetImpl(
            managers.spend_budget_gate,
            managers.pricing,
            managers.agent_sessions,
            managers.spend_budgets,
            agent_projects=SessionAgentProjectsBoundImpl(storage.get_agent_project_storage()),
        ),
        CallCredentialsPlatformImpl(providers),
        infra.get_outages(),
        sink,
        catalog,
        LoopOptions(control_poll=timedelta(milliseconds=1)),
        clock,
        sleep,
        leases=managers.leases,
        hooks=LoopHooksNullImpl(),
    )
    return Trusted(
        infra=infra,
        storage=storage,
        managers=managers,
        trust=trust,
        trust_options=layer.options,
        loops=loops,
        anthropic=anthropic,
        sink=sink,
        clock=clock,
        owner=owner or context(Role.OWNER, make_org()),
        transition=transition,
        placement=placement,
        probe=probe,
        lookup=lookup,
    )
