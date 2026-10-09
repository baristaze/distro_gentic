from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.placement_storage import PlacementStorageContract, WrittenBefore, make_share
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from acme.infra.impl.local import InfraLocalImpl
from acme.om.base import new_id, utcnow
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    OperatorContext,
    OperatorRole,
    RequestContext,
    TenantContext,
)
from acme.om.placement.impl.manager import PlacementOptions
from acme.om.placement.rules import tier_lane
from acme.om.placement.storage import PlacementStorageInterface
from acme.om.placement.storage.impl.postgres import PlacementStoragePostgresImpl
from acme.om.placement.types.share import FairShare
from acme.om.root import Managers, build_managers
from acme.om.storage.impl.pg_base import LoginSessions
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.roles import DatabaseRole
from acme.om.storage.settings import MigrationSettings
from acme.om.tenancy.rules import operator_permissions_of
from acme.om.work.types.work_item import WorkItem, WorkKind

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.WORKER, version="worker@test")
LEASE = timedelta(seconds=60)

# The insert the release before makes: every column it maps, the
# concurrency among them, and no marker, so the row is not carried.
WRITTEN_BEFORE = text(
    "INSERT INTO core.fair_shares (id, org_id, created_at, updated_at, created_by,"
    " updated_by, plan_tier, own_lane, concurrency, version) VALUES (:id, :org_id,"
    " :created_at, :updated_at, :created_by, :updated_by, :plan_tier, :own_lane,"
    " :concurrency, :version)"
)


async def write_before(url: str, org_id: UUID, share: FairShare, concurrency: int) -> None:
    """Lands the share as the release before wrote it, under the migration
    login at `url`, in the tenant's own scope, which the fence admits."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.org_id', :org_id, true)"), {"org_id": str(org_id)}
            )
            await connection.execute(
                WRITTEN_BEFORE,
                {**share.model_dump(), "org_id": org_id, "concurrency": concurrency},
            )
    finally:
        await engine.dispose()


class TestPlacementStoragePostgres(PlacementStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> PlacementStorageInterface:
        return PlacementStoragePostgresImpl(pg_sessions)

    @pytest.fixture
    def written_before(self, migrated: dict[DatabaseRole, str]) -> WrittenBefore:
        async def write(org_id: UUID, share: FairShare, concurrency: int) -> None:
            await write_before(migrated[DatabaseRole.CORE], org_id, share, concurrency)

        return write


@pytest.fixture
async def managers(
    migration_settings: MigrationSettings, migrated: object, tmp_path: Path
) -> AsyncIterator[Managers]:
    root = StoragePostgresImpl(
        migration_settings.role_urls(),
        migration_settings.role_pools(),
        system_urls=migration_settings.system_role_urls(),
    )
    yield build_managers(root, InfraLocalImpl(tmp_path))
    await root.close()


async def test_the_sweeps_carry_makes_a_shares_concurrency_the_cap_the_claim_holds(
    managers: Managers, migrated: dict[DatabaseRole, str]
) -> None:
    """Ann's share, as the release before wrote it, ran one loop at once.
    The carry writes that as Ann's own cap on its tier's lane, once, and
    the claim holds it in place of the tier's share of eight: Ann's second
    loop waits, unwritten, while Bob's is claimed."""
    rctx = RequestContext(request_id=new_id(), app=APP)
    owners = []
    for name in ("ann", "bob"):
        slug = f"{name}-{new_id().hex[-8:]}"
        owner, _ = await managers.tenancy.bootstrap(rctx, name, slug, f"{slug}@example.test", "A")
        owners.append(owner)
    ann, bob = owners
    await write_before(migrated[DatabaseRole.CORE], ann.org_id, make_share(plan_tier="pro"), 1)

    assert await managers.placement_operator.carry_caps(100) == 1
    assert await managers.placement_operator.carry_caps(100) == 0, "once"

    lane = tier_lane("pro")
    for owner in (ann, ann):
        await managers.work.enqueue(owner, a_loop(owner))
    await managers.placement_operator.set_share(
        an_operator(), bob.org_id, plan_tier="pro", own_lane=False
    )
    await managers.work.enqueue(bob, a_loop(bob))
    claimed = []
    for _ in range(3):
        found = await managers.work.claim(
            rctx, lane, [WorkKind.LOOP], "runner", LEASE, PlacementOptions().lane_cap(lane)
        )
        claimed.append(None if found is None else found[0].org_id)
    assert claimed == [ann.org_id, bob.org_id, None], "Ann waits at its carried cap of one"


def an_operator() -> OperatorContext:
    return OperatorContext(
        request_id=new_id(),
        app=AppContext(type=AppType.CLI, version="ops@test"),
        identity_id=new_id(),
        email="root@example.test",
        credential_kind=CredentialKind.LOGIN,
        credential_id=new_id(),
        permissions=operator_permissions_of(OperatorRole.WRITE),
    )


def a_loop(ctx: TenantContext) -> WorkItem:
    now = utcnow()
    return WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        kind=WorkKind.LOOP,
        target_id=new_id(),
        idempotency_key=new_id(),
        request_id=new_id(),
        payload={},
        lane="default",
        available_at=now,
    )
