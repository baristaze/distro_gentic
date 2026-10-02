"""The runner holds its tenant's fair share at the claim: a claimed loop
over the share goes back to its lane with a delay, its attempt given back,
and never runs. Over memory, and over Postgres, where the count of the
loops ahead is one statement on the queue's claimed rows."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from runner_support import ABSENT

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
)
from acme.om.placement.rules import tier_lane
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
OVER_SHARE = timedelta(seconds=15)
"""The delay placement names by default."""


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


async def test_a_loop_over_its_tenants_share_goes_back_to_its_lane_with_no_attempt_spent(
    storage: StorageInterface, tmp_path: Path
) -> None:
    container = RunnerContainer.over(
        SessionRunnerSettings.model_validate(
            {"_env_file": None, "environment": "test", "runner_id": "runner-test"}
        ),
        storage,
        InfraLocalImpl(tmp_path),
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        agent_kinds=ABSENT,
    )
    managers = container.managers
    rctx = RequestContext(request_id=new_id(), app=APP)
    slug = f"ajax-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(rctx, "Ajax", slug, f"ann@{slug}.test", "Ann")
    # A tier of its own, so no loop of another case shares the lane.
    tier = f"t{new_id().hex[-8:]}"
    await managers.placement_operator.set_share(
        operator(), owner.org_id, plan_tier=tier, own_lane=False, concurrency=1
    )
    lane = tier_lane(tier)
    enqueued = Enqueued(owner.org_id)
    container.infra.get_topics().subscribe(Topics.WORK_AVAILABLE, "case", enqueued.record)
    for question in ("Why does it drop the object?", "Why does it stall?"):
        session = await managers.agents.start_session(
            owner, Start(id=new_id(), kind="assistant", title=question)
        )
        said = message_step(new_id(), utcnow(), session.id, owner, question)
        await managers.agent_sessions.receive(owner, session.id, [said])
    # Another runner holds the tenant's one loop at once.
    held = await managers.work.claim(rctx, lane, [WorkKind.LOOP], "runner-elsewhere", LEASE)
    assert held is not None

    before = utcnow()
    runner = build_runner(container, lane)
    running = asyncio.create_task(runner.run())
    try:
        for _ in range(500):
            items = await enqueued.items(storage)
            waiting = [i for i in items if i.id != held[1].id]
            if waiting and (waiting[0].last_error or "").startswith("parked"):
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("the runner never sent the loop back")
    finally:
        runner.stop()
        await running

    assert len(enqueued.keys) == 2
    items = {i.id: i for i in await enqueued.items(storage)}
    (back,) = [i for i in items.values() if i.id != held[1].id]
    assert (back.status, back.attempts, back.lane, back.claimed_by) == (
        WorkStatus.QUEUED,
        0,
        lane,
        None,
    ), "back in its lane, the claim's attempt given back"
    assert back.available_at >= before + OVER_SHARE, "after the delay, not at once"
    assert back.last_error == "parked: its tenant runs as many loops as its share allows"
    assert items[held[1].id].status is WorkStatus.CLAIMED, "the loop ahead runs on"
