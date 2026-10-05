"""A member's removal unlinks their outside accounts over Postgres, as the
worker runs it: the removal's commit queues the work, the relay enqueues
it, the worker claims it and unlinks under the tenant's own login, and
the account links again to the person added back."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from worker_support import request, sign_in

from acme.om.base import new_id
from acme.om.context import Role, TenantContext
from acme.om.work.types.work_item import WorkItem, WorkKind
from acme.workers.maintenance.container import WorkerContainer
from acme.workers.maintenance.main import build_loop
from acme.workers.maintenance.settings import MaintenanceSettings

pytestmark = pytest.mark.integration

LEASE = timedelta(seconds=30)


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[WorkerContainer]:
    settings = MaintenanceSettings(
        cache_backend="memory",
        topics_backend="memory",
        buckets_backend="local",
        buckets_root=tmp_path / "buckets",
        queues_backend="memory",
        secrets_backend="local",
        sentry_dsn=None,
        otel_endpoint=None,
        worker_id="member-left-integration",
    )
    settings.refuse_remote()
    built = WorkerContainer.build(settings)
    yield built
    await built.close()


async def test_a_removed_members_links_go_over_postgres(container: WorkerContainer) -> None:
    tail = new_id().hex[-8:]
    slug, email = f"left-{tail}", f"bob-{tail}@example.test"
    tenancy, intake, work = container.managers.tenancy, container.intake, container.managers.work
    links = container.storage.get_intake_storage()
    ann = await sign_in(container, slug)
    _, bob, _ = await tenancy.add_member(request(), slug, email, "Bob", Role.MEMBER)
    chat, forge = f"U-{tail}", f"bob-{tail}"
    await intake.link_account(ann, "chat", chat, bob.id)
    await intake.link_account(ann, "forge", forge, bob.id)

    await tenancy.members.remove_member(ann, bob.id)
    # The queue is the database's: an item another test left goes back.
    others: list[tuple[TenantContext, WorkItem]] = []
    while True:
        claimed = await work.claim(request(), "default", [WorkKind.MEMBER_LEFT], "it", LEASE)
        assert claimed is not None, "the removal queued its work"
        ctx, item = claimed
        if item.target_id == bob.id:
            break
        others.append(claimed)
    for other_ctx, other in others:
        await work.release(other_ctx, other)
    assert ctx.org_id == ann.org_id
    await build_loop(container)._handlers[item.kind].handle(ctx, item)  # pyright: ignore[reportPrivateUsage]
    await work.complete(ctx, item)

    assert await links.read_link(ann.org_id, "chat", chat) is None
    assert await links.read_link(ann.org_id, "forge", forge) is None
    _, again, _ = await tenancy.add_member(request(), slug, email, "Bob", Role.MEMBER)
    assert (await intake.link_account(ann, "chat", chat, again.id)).user_id == again.id
