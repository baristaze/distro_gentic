"""What a local run needs of the platform before a session's first model
call, seeded beside the tenant `bootstrap` writes: the tenant's account on
a published plan, its first project, its retention policy, and a published
version of the model matrix. Each step answers what is there already, so a
seed run twice writes nothing new. A development seed only: it qualifies
the engine's own fills by a recorded run, which no deployed matrix takes."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.agents.types.kind import AgentKind
from acme.om.base import new_id, utcnow
from acme.om.billing.root import build_billing
from acme.om.billing.types.account import AccountRequest, FundingMode
from acme.om.context import OperatorContext, OperatorRole, RequestContext, TenantContext
from acme.om.matrix.root import MatrixLayer, engine_rows
from acme.om.matrix.types.matrix import MatrixStatus
from acme.om.matrix.types.record import BenchmarkRun
from acme.om.models.types.fill import MAIN, SUMMARIZER
from acme.om.platform_agents.kinds import SHIPPED
from acme.om.projects.types.project import Project, Repository
from acme.om.retention.types.policy import RetentionPolicy
from acme.om.root import Managers
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.rules import PLATFORM_EMAIL_DOMAIN

PLAN = "starter"
"""The plan a seeded tenant's account opens on."""

REPOSITORY = Repository(host="example.test", path="acme/first")
"""The repository a seeded tenant's first project binds."""

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
    project: Project | None
    """The first project, None when the tenant's account was there already."""
    matrix_version: int


@asynccontextmanager
async def seed_operator(managers: Managers, rctx: RequestContext) -> AsyncIterator[OperatorContext]:
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
    managers: Managers,
    rctx: RequestContext,
    kinds: Sequence[AgentKind],
) -> int:
    """The published version of the matrix, published by the seed when
    none is: every model role the engine, the platform's agents, and
    `kinds` call, and every fill qualified for every role its row serves."""
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
        for row in version.rows:
            for fill in row.fills:
                for role in version.roles_of(row):
                    run = BenchmarkRun(
                        provider=fill.provider,
                        model=fill.model,
                        role=role,
                        benchmark=BENCHMARK,
                        passed=True,
                        run=f"{BENCHMARK}-{new_id().hex[:8]}",
                    )
                    await operators.record_benchmark(admin, run)
        return (await operators.publish(admin, version.number)).number


async def seed_platform(
    storage: StorageInterface,
    managers: Managers,
    owner: TenantContext,
    kinds: Sequence[AgentKind] = (),
) -> Seeded:
    """The owner's tenant made ready to run a session: its account on the
    starter plan, paid on the platform's key; its first project; its
    retention policy; and the matrix, published once for every tenant.
    `kinds` are the product's, beside the ones the platform ships."""
    project = None
    if await storage.get_account_storage().read_account(owner.org_id) is None:
        # The project before the account: a run cut short between them
        # leaves a second project on the rerun, never a tenant with none.
        project = await managers.projects.create_project(owner, first_project(owner))
        billing = build_billing(storage, managers, PaymentProviderTwinImpl())
        request = AccountRequest(funding=FundingMode.PLATFORM, plan_id=PLAN, zone="UTC")
        await billing.open_account(owner, request)
    policy = await managers.retention.get_policy(owner)
    if policy.version == 0:
        await managers.retention.write_policy(
            owner,
            policy.model_copy(
                update={"policy": RetentionPolicy(content_lifetime=CONTENT_LIFETIME)}
            ),
        )
    version = await seed_matrix(storage, managers, owner, kinds)
    return Seeded(project=project, matrix_version=version)


def first_project(owner: TenantContext) -> Project:
    """The tenant's first project, bound to the seed's repository."""
    now = utcnow()
    return Project(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=owner.user_id,
        updated_by=owner.user_id,
        name="First project",
        repository=REPOSITORY,
    )
