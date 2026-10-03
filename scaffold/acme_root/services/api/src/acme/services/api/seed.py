"""What a local run needs of the platform before a session's first model
call, seeded beside the tenant `bootstrap` writes: the tenant's account on
a published plan, its first project, its retention policy, and a published
version of the model matrix. Each step answers what is there already, so a
seed run twice writes nothing new. A development seed only: it qualifies
the engine's own fills by a recorded run, which no deployed matrix takes."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.agents.types.kind import AgentKind
from acme.om.base import new_id, utcnow
from acme.om.billing.impl.manager import BillingManagerImpl
from acme.om.billing.types.account import AccountRequest, FundingMode
from acme.om.billing.types.plan import PLANS, UNITS
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    OperatorContext,
    OperatorRole,
    TenantContext,
)
from acme.om.matrix.root import MatrixLayer
from acme.om.matrix.types.matrix import MatrixKey, MatrixRow, MatrixStatus
from acme.om.matrix.types.record import BenchmarkRun
from acme.om.models.impl.resolver import DEFAULT_TABLE
from acme.om.models.types.fill import MAIN, SUMMARIZER
from acme.om.platform_agents.kinds import SHIPPED
from acme.om.projects.types.project import Project, Repository
from acme.om.retention.types.policy import RetentionPolicy
from acme.om.root import Managers
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.rules import operator_permissions_of

PLAN = "starter"
"""The plan a seeded tenant's account opens on."""

REPOSITORY = Repository(host="example.test", path="acme/first")
"""The repository a seeded tenant's first project binds."""

CONTENT_LIFETIME = timedelta(days=30)
"""How long a seeded tenant keeps what a session says."""

BENCHMARK = "local-seed"
"""The run a seed records for each fill it qualifies."""


@dataclass(frozen=True)
class Seeded:
    project: Project
    matrix_version: int


def seed_operator() -> OperatorContext:
    """The operator the seed publishes the matrix as, in this process alone."""
    return OperatorContext(
        request_id=new_id(),
        app=AppContext(type=AppType.CLI, version="acme-api@seed"),
        identity_id=new_id(),
        email="seed@example.test",
        credential_kind=CredentialKind.LOGIN,
        credential_id=new_id(),
        permissions=operator_permissions_of(OperatorRole.WRITE),
    )


def seed_rows() -> tuple[MatrixRow, ...]:
    """The engine's own table as a matrix: a row for each of its roles,
    and its first fill and fallbacks again as the row that matches every
    question, so every role a kind names has an answer."""
    rows = [
        MatrixRow(key=MatrixKey(role=entry.role), fills=(entry.fill, *entry.fallbacks))
        for entry in DEFAULT_TABLE
    ]
    first = DEFAULT_TABLE[0]
    return (*rows, MatrixRow(fills=(first.fill, *first.fallbacks)))


async def seed_matrix(
    storage: StorageInterface, managers: Managers, kinds: Sequence[AgentKind]
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
    admin = seed_operator()
    version = await operators.stage(admin, roles, seed_rows())
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
    accounts = storage.get_account_storage()
    if await accounts.read_account(owner.org_id) is None:
        billing = BillingManagerImpl(
            accounts,
            storage.get_money_ledger_storage(),
            managers.budgets,
            managers.agent_sessions,
            PaymentProviderTwinImpl(),
            managers.outbox,
            PLANS,
            UNITS,
        )
        request = AccountRequest(funding=FundingMode.PLATFORM, plan_id=PLAN, zone="UTC")
        await billing.open_account(owner, request)
    project = await managers.projects.create_project(owner, first_project(owner))
    policy = await managers.retention.get_policy(owner)
    if policy.version == 0:
        await managers.retention.write_policy(
            owner,
            policy.model_copy(
                update={"policy": RetentionPolicy(content_lifetime=CONTENT_LIFETIME)}
            ),
        )
    return Seeded(project=project, matrix_version=await seed_matrix(storage, managers, kinds))


def first_project(owner: TenantContext) -> Project:
    """The tenant's first project, by an id its tenant names, so a seed run
    twice answers the one written."""
    now = utcnow()
    return Project(
        id=project_id_of(owner.org_id),
        created_at=now,
        updated_at=now,
        created_by=owner.user_id,
        updated_by=owner.user_id,
        name="First project",
        repository=REPOSITORY,
    )


def project_id_of(org_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"acme:seed:project:{org_id}")
