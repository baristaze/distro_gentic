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
from acme.om.agents.impl.loop import LoopManagerImpl, LoopOptions
from acme.om.agents.impl.sink import StreamSinkMemoryImpl
from acme.om.agents.types.kind import AgentKind, AgentKindCatalog, DoneRule, TreeLimits
from acme.om.agents.types.request import Start
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import new_id
from acme.om.budgets.types.amount import Amount
from acme.om.context import (
    CredentialKind,
    RequestContext,
    Role,
    TenantContext,
    build_context,
)
from acme.om.exceptions import NotAuthorized
from acme.om.models.impl.credentials import CallCredentialsPlatformImpl
from acme.om.projects.impl.policies import SessionProjectsBoundImpl
from acme.om.projects.types.project import Project
from acme.om.root import Managers, ProductKinds, build_managers
from acme.om.steps.types.step import Step
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.rules import permissions_of
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.policy import Decision, PolicyLayer, PolicyRule
from acme.om.tools.types.tool import Effect, ToolClass
from acme.om.trust.impl.keys import KeyProbeTwinImpl
from acme.om.trust.impl.manager import TrustOptions
from acme.om.trust.keys import ClientFactory
from acme.om.trust.placement import PlacementInterface
from acme.om.trust.root import TrustLayer, TrustManagers, absent_client
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.windows.impl.gate import CallGateBudgetImpl
from contracts.doubles import APP, context
from contracts.factories import make_org
from contracts.loops import Clock, Lookup
from contracts.project_storage import make_binding, make_project
from contracts.step_storage import make_message
from contracts.tools import INJECTED_TOKEN, TWIN_SPEC, Command

ALLOWED = PolicyLayer(
    rules=(
        PolicyRule(authorization_class=ToolClass.READ, decision=Decision.ALLOW),
        PolicyRule(authorization_class=ToolClass.EXECUTE, decision=Decision.ALLOW),
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
            credential_kind=CredentialKind.SESSION_TOKEN,
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

    async def inside_wall(self, org_id: UUID, session_id: UUID) -> bool:
        return session_id in self.walled

    async def executor_of(self, org_id: UUID, session_id: UUID) -> Executor:
        return self.host if session_id in self.walled else self.cloud


@dataclass
class Trusted:
    infra: InfraLocalImpl
    storage: StorageInterface
    managers: Managers
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
    # The owner's project, where a suite's sessions start and its secrets
    # are declared.
    project: Project = field(default_factory=make_project)

    @property
    def transport(self) -> TransportTwinImpl:
        transport = self.infra.get_transport()
        assert isinstance(transport, TransportTwinImpl)
        return transport

    def member(self) -> TenantContext:
        """Another member of the owner's tenant."""
        return build_context(
            RequestContext(request_id=new_id(), app=APP),
            user_id=new_id(),
            org_id=self.owner.org_id,
            role=Role.MEMBER,
            permissions=permissions_of(Role.MEMBER),
            credential_kind=CredentialKind.SESSION_TOKEN,
        )

    async def owners_project(self) -> UUID:
        """The owner's project, written on its first use."""
        projects = self.storage.get_project_storage()
        await projects.create_project(self.owner.org_id, self.project, ())
        return self.project.id

    async def start(
        self, ctx: TenantContext | None = None, kind: str = "steady", *, project: bool = False
    ) -> UUID:
        """A session of no project, or of the owner's. Its project's row is
        written once it stands, so no workspace checks the project out."""
        session = await self.managers.agents.start_session(
            ctx or self.owner, Start(id=new_id(), kind=kind, title="the records")
        )
        if project:
            binding = make_binding(session.id, await self.owners_project())
            await self.storage.get_project_storage().bind_session(self.owner.org_id, binding)
        return session.id

    async def say(self, session_id: UUID, text: str, ctx: TenantContext | None = None) -> Step:
        ctx = ctx or self.owner
        person = Principal(kind=PrincipalKind.PERSON, id=ctx.user_id)
        message = make_message(session_id, text, principal=person)
        (stored,) = await self.managers.steps.append_inputs(ctx, session_id, [message])
        return stored

    async def history(self, session_id: UUID) -> list[Step]:
        steps: list[Step] = []
        while True:
            after = steps[-1].seq if steps else 0
            page = await self.managers.steps.get_steps(self.owner, session_id, after, 200)
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
    managers = build_managers(
        storage,
        infra,
        integrations=IntegrationsOverImpl(IdentityProviderAbsentImpl(), providers),
        agent_kinds=(STEADY,),
        principal_context=transition,
        tool_catalog=catalog,
        tools_layer=layer.tools,
        product_kinds=product_kinds,
    )
    trust = layer.build(managers)

    async def sleep(seconds: float) -> None:
        clock.now += timedelta(seconds=seconds)
        await asyncio.sleep(0)

    sink = StreamSinkMemoryImpl()
    loops = LoopManagerImpl(
        managers.steps,
        managers.agent_sessions,
        managers.agents,
        AgentKindCatalog(kinds=(STEADY,)),
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
        sink,
        catalog,
        LoopOptions(control_poll=timedelta(milliseconds=1)),
        clock,
        sleep,
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
