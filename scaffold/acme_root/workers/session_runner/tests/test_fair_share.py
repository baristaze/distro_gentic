"""The runner holds each tenant to its tier's share at the claim: its lane
passes the tier's share as the claim's cap, so a tenant that holds its
share of the lane is passed over while another tenant's loop is claimed,
and its waiting loop is not written and spends no attempt. Over memory,
and over Postgres, where the pass-over is the claim's one statement."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from runner_support import ABSENT, TOOLS

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.topics import TopicPayload, Topics, WorkAvailablePayload
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.om.agents.types.request import Start
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
from acme.om.root import PlatformPorts, ProductKinds
from acme.om.steps.rules import message_step
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.root import StorageInterface
from acme.om.storage.settings import MigrationSettings
from acme.om.tenancy.rules import operator_permissions_of
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus
from acme.workers.session_runner.container import RunnerContainer
from acme.workers.session_runner.main import build_runner
from acme.workers.session_runner.settings import SessionRunnerSettings

APP = AppContext(type=AppType.PORTAL, version="portal@test")
LEASE = timedelta(seconds=60)


def operator() -> OperatorContext:
    return OperatorContext(
        request_id=new_id(),
        app=AppContext(type=AppType.CLI, version="ops@test"),
        identity_id=new_id(),
        email="root@example.test",
        credential_kind=CredentialKind.LOGIN,
        credential_id=new_id(),
        permissions=operator_permissions_of(OperatorRole.WRITE),
    )


@pytest.fixture(
    params=["memory", pytest.param("postgres", marks=pytest.mark.integration)],
)
async def storage(request: pytest.FixtureRequest) -> AsyncIterator[StorageInterface]:
    if request.param == "memory":
        yield StorageMemoryImpl()
        return
    settings = MigrationSettings()
    settings.refuse_remote()
    root = StoragePostgresImpl(
        settings.role_urls(), settings.role_pools(), system_urls=settings.system_role_urls()
    )
    yield root
    await root.close()


class Enqueued:
    """The keys of the loops enqueued for one tenant, off the wake each
    enqueue publishes, so the items read back under the tenant's fence."""

    def __init__(self, org_id: UUID) -> None:
        self.org_id = org_id
        self.keys: list[UUID] = []

    async def record(self, payload: TopicPayload) -> None:
        if (
            isinstance(payload, WorkAvailablePayload)
            and payload.org_id == self.org_id
            and payload.kind == WorkKind.LOOP.value
        ):
            self.keys.append(payload.idempotency_key)

    async def items(self, storage: StorageInterface) -> list[WorkItem]:
        work = storage.get_work_storage()
        found = [await work.read_item_by_key(self.org_id, key) for key in self.keys]
        return [item for item in found if item is not None]


async def test_a_tenant_at_its_tiers_share_is_passed_over_while_anothers_loop_is_claimed(
    storage: StorageInterface, tmp_path: Path
) -> None:
    # A tier of its own, so no loop of another case shares the lane, with a
    # share of one loop a tenant.
    tier = f"t{new_id().hex[-8:]}"
    container = RunnerContainer.over(
        SessionRunnerSettings.model_validate(
            {"_env_file": None, "environment": "test", "runner_id": "runner-test"}
        ),
        storage,
        InfraLocalImpl(tmp_path),
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        ports=PlatformPorts(kinds=ProductKinds(agents=ABSENT, tools=lambda _managers: TOOLS)),
        placement_options=PlacementOptions(tier_shares={tier: 1}),
    )
    managers = container.managers
    rctx = RequestContext(request_id=new_id(), app=APP)
    lane = tier_lane(tier)

    async def a_tenant(name: str, questions: tuple[str, ...]) -> tuple[TenantContext, Enqueued]:
        slug = f"{name}-{new_id().hex[-8:]}"
        owner, _ = await managers.tenancy.bootstrap(
            rctx, name.title(), slug, f"ann@{slug}.test", "Ann"
        )
        # The tier alone: no cap of its own, so the tier's share holds.
        await managers.placement_operator.set_share(
            operator(), owner.org_id, plan_tier=tier, own_lane=False
        )
        enqueued = Enqueued(owner.org_id)
        container.infra.get_topics().subscribe(Topics.WORK_AVAILABLE, name, enqueued.record)
        for question in questions:
            session = await managers.agents.start_session(
                owner, Start(id=new_id(), kind="assistant", title=question)
            )
            said = message_step(new_id(), utcnow(), session.id, owner, question)
            await managers.agent_sessions.receive(owner, session.id, [said])
        return owner, enqueued

    _, ajax = await a_tenant("ajax", ("Why does checkout time out?", "Why does it stall?"))
    # Another runner of the lane holds Ajax's first loop: its share of one.
    held = await managers.work.claim(
        rctx, lane, [WorkKind.LOOP], "runner-elsewhere", LEASE, tenant_cap=1
    )
    assert held is not None and held[0].org_id == ajax.org_id
    _, beta = await a_tenant("beta", ("Why is the build red?",))

    runner = build_runner(container, lane)
    running = asyncio.create_task(runner.run())
    try:
        for _ in range(500):
            claimed = [i for i in await beta.items(storage) if i.attempts > 0]
            if claimed:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("the runner never claimed the other tenant's loop")
    finally:
        runner.stop()
        await running

    assert len(ajax.keys) == 2
    items = {i.id: i for i in await ajax.items(storage)}
    (waiting,) = [i for i in items.values() if i.id != held[1].id]
    assert (waiting.status, waiting.attempts, waiting.lane, waiting.claimed_by) == (
        WorkStatus.QUEUED,
        0,
        lane,
        None,
    ), "passed over in its lane, no attempt spent"
    assert waiting.last_error is None, "never claimed, so never written"
    assert items[held[1].id].status is WorkStatus.CLAIMED, "the loop ahead runs on"
    (theirs,) = await beta.items(storage)
    assert theirs.attempts == 1, "the other tenant's loop was claimed"
