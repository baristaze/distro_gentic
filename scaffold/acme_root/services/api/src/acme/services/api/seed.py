"""What a local run needs of the platform before a session's first model
call, seeded beside the tenant `bootstrap` writes: the tenant's account on
a published plan, its first agent project, its retention policy, a published
version of the model matrix, and, where the forge is its twin, the twin's
installation that holds the first agent project's repository, connected to the
tenant. Each step answers what is there already, so a seed run twice
writes nothing new. A development seed only: it qualifies the engine's own
fills by a recorded run, which no deployed matrix takes."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from acme.integrations.events import IntegrationInterface
from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.agent_billing.root import build_agent_billing
from acme.om.agent_billing.types.spend_account import FundingMode, SpendAccountRequest
from acme.om.agent_projects.types.agent_project import AgentProject, Repository
from acme.om.agents.types.kind import AgentKind
from acme.om.base import new_id, utcnow
from acme.om.context import OperatorContext, OperatorRole, RequestContext, TenantContext
from acme.om.exceptions import Conflict
from acme.om.intake.types.link import Installation
from acme.om.language_models.types.fill import MAIN, SUMMARIZER
from acme.om.matrix.root import MatrixLayer, engine_rows
from acme.om.matrix.types.matrix import MatrixStatus
from acme.om.matrix.types.record import BenchmarkRun
from acme.om.platform_agents.kinds import SHIPPED
from acme.om.platform_root import PlatformManagers
from acme.om.retention.types.policy import RetentionPolicy
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.rules import PLATFORM_EMAIL_DOMAIN

UNIT_PLAN = "starter"
"""The plan a seeded tenant's account opens on."""

REPOSITORY_HOST = "example.test"
"""The host of the repository a seeded tenant's first agent project binds."""

FORGE = "forge"
"""The integration that holds a session's work."""

CONTENT_LIFETIME = timedelta(days=30)
"""How long a seeded tenant keeps what a session says."""

BENCHMARK = "local-seed"
"""The run a seed records for each fill it qualifies."""

PROVISIONER = f"provisioner@{PLATFORM_EMAIL_DOMAIN}"
"""The platform's own write operator, which `make seed` grants too: the
seed publishes the matrix as it."""

TOKEN_LIFE = timedelta(minutes=1)
"""How long the operator token the seed mints for itself may live; the seed
ends it once the matrix is published."""


@dataclass(frozen=True)
class Seeded:
    agent_project: AgentProject | None
    """The first agent project, None when the tenant's account was there already."""
    matrix_version: int


@asynccontextmanager
async def seed_operator(
    managers: PlatformManagers, rctx: RequestContext
) -> AsyncIterator[OperatorContext]:
    """The provisioner, admitted as the grant job admits it: put on the
    allowlist with write, and admitted on an operator token the seed mints,
    holds in this process alone, and ends when it is done."""
    tenancy = managers.tenancy
    await tenancy.grant_operator(rctx, PROVISIONER, OperatorRole.WRITE)
    issued = await tenancy.grant_operator_token(rctx, PROVISIONER, TOKEN_LIFE)
    admin = await tenancy.admit_operator(await tenancy.authenticate_login(rctx, issued.token))
    try:
        yield admin
    finally:
        await managers.tenancy_operator.revoke_operator_token(admin, issued.id)


async def seed_matrix(
    storage: StorageInterface,
    managers: PlatformManagers,
    rctx: RequestContext,
    kinds: Sequence[AgentKind],
) -> int:
    """The published version of the matrix, published by the seed when
    none is: every model role the engine, the platform's agents, and
    `kinds` call, a row for each of the engine's model sizes, and every
    fill qualified for every role its row serves."""
    roles = sorted(
        {MAIN, SUMMARIZER, *(role for kind in (*SHIPPED, *kinds) for role in kind.roles)}
    )
    layer = MatrixLayer(storage)
    published = await storage.get_matrix_storage().read_latest(MatrixStatus.PUBLISHED)
    if published is not None:
        return published.number
    operators = layer.build(managers).matrix_operator
    async with seed_operator(managers, rctx) as admin:
        version = await operators.stage(admin, roles, engine_rows())
        # One run for each model and each role a row of it serves, however
        # many rows name the model.
        qualified = dict.fromkeys(
            (fill.provider, fill.model, role)
            for row in version.rows
            for fill in row.fills
            for role in version.roles_of(row)
        )
        for provider, model, role in qualified:
            run = BenchmarkRun(
                provider=provider,
                model=model,
                role=role,
                benchmark=BENCHMARK,
                passed=True,
                run=f"{BENCHMARK}-{new_id().hex[:8]}",
            )
            await operators.record_benchmark(admin, run)
        return (await operators.publish(admin, version.number)).number


async def seed_platform(
    storage: StorageInterface,
    managers: PlatformManagers,
    owner: TenantContext,
    kinds: Sequence[AgentKind] = (),
    *,
    forge: IntegrationInterface | None = None,
) -> Seeded:
    """The owner's tenant made ready to run a session: its account on the
    starter plan, paid on the platform's key; its first agent project; its
    retention policy; the matrix, published once for every tenant; and,
    when `forge` is the forge's twin, the twin's installation that holds the
    first agent project's repository, connected to the tenant as its installer
    would. `kinds` are the product's, beside the ones the platform ships."""
    slug = (await managers.tenancy.org.get_org(owner)).slug
    agent_project = None
    if await storage.get_spend_account_storage().read_spend_account(owner.org_id) is None:
        # The agent project before the account: a run cut short between them
        # leaves a second agent project on the rerun, never a tenant with none.
        agent_project = await managers.agent_projects.create_agent_project(
            owner, first_agent_project(owner, slug)
        )
        agent_billing = build_agent_billing(storage, managers, PaymentProviderTwinImpl())
        request = SpendAccountRequest(
            funding=FundingMode.PLATFORM, unit_plan_id=UNIT_PLAN, zone="UTC"
        )
        await agent_billing.open_spend_account(owner, request)
    policy = await managers.retention.get_policy(owner)
    if policy.version == 0:
        await managers.retention.write_policy(
            owner,
            policy.model_copy(
                update={"policy": RetentionPolicy(content_lifetime=CONTENT_LIFETIME)}
            ),
        )
    version = await seed_matrix(storage, managers, owner, kinds)
    if forge is not None and forge.provenance == "twin":
        await connect_forge_twin(storage, owner, forge, first_repository(slug))
    return Seeded(agent_project=agent_project, matrix_version=version)


async def connect_forge_twin(
    storage: StorageInterface,
    owner: TenantContext,
    forge: IntegrationInterface,
    repository: Repository,
) -> Installation:
    """The forge twin's installation that holds `repository`, connected to
    the owner's tenant, or the one the tenant connected already. A real
    forge's installation is connected by the person who installed it; the
    twin's has no such person, so the seed connects it as the owner.
    `Conflict` when another tenant holds it."""
    named = await forge.installation_of(f"https://{repository.host}/{repository.path}.git")
    installation = Installation(
        id=new_id(),
        created_at=utcnow(),
        integration=FORGE,
        installation=named,
        created_by=owner.user_id,
    )
    held = await storage.get_intake_storage().create_installation(owner.org_id, installation)
    if held is None:
        raise Conflict(f"{FORGE} installation {named} is another tenant's")
    return held


def first_repository(slug: str) -> Repository:
    """The repository the first agent project of the tenant `slug` binds,
    `example.test/<slug>/first`: under an owner of the tenant's own, so the
    forge twin's installation that holds it is the tenant's alone."""
    return Repository(host=REPOSITORY_HOST, path=f"{slug}/first")


def first_agent_project(owner: TenantContext, slug: str) -> AgentProject:
    """The first agent project of the tenant `slug`, bound to its seeded
    repository."""
    now = utcnow()
    return AgentProject(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=owner.user_id,
        updated_by=owner.user_id,
        name="First agent project",
        repository=first_repository(slug),
    )
