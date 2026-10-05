"""A person's place in a team org ends, by their removal or by their
account's deletion, and the queue unlinks every outside account linked to
them there: none of their ids stays linked, the account links again to the
person added back, and a member who stays keeps theirs."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from worker_support import build_container, request, sign_in, signing

from acme.om.context import Role, TenantContext
from acme.om.exceptions import NotFound
from acme.om.tenancy.types.user import User
from acme.om.work.types.work_item import WorkKind
from acme.workers.maintenance.container import WorkerContainer
from acme.workers.maintenance.main import build_loop

LEASE = timedelta(seconds=30)


async def add_bob(container: WorkerContainer) -> User:
    _, bob, _ = await container.managers.tenancy.add_member(
        request(), "ajax", "bob@example.test", "Bob", Role.MEMBER
    )
    return bob


async def bob_signs_in(container: WorkerContainer, org_id: UUID) -> TenantContext:
    """Bob's own session in the org, by address."""
    tenancy = container.managers.tenancy
    login = await signing(container).sign_in.dev_sign_in(request(), "bob@example.test")
    identity = await tenancy.authenticate_login(request(), login.token)
    issued = await tenancy.sign_in.exchange_login(identity, org_id)
    return await tenancy.authenticate(request(), issued.token)


async def run_member_left(container: WorkerContainer) -> None:
    """The MEMBER_LEFT item the commit queued, run as the worker runs it."""
    work = container.managers.work
    claimed = await work.claim(request(), "default", [WorkKind.MEMBER_LEFT], "test", LEASE)
    assert claimed is not None
    ctx, item = claimed
    await build_loop(container)._handlers[item.kind].handle(ctx, item)  # pyright: ignore[reportPrivateUsage]
    await work.complete(ctx, item)
    # One item a place that ended: nothing else is queued.
    assert await work.claim(request(), "default", [WorkKind.MEMBER_LEFT], "test", LEASE) is None


async def test_a_removed_member_leaves_no_link_and_links_again_once_back(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    tenancy, intake = container.managers.tenancy, container.intake
    links = container.storage.get_intake_storage()
    ann = await sign_in(container)
    bob = await add_bob(container)
    await intake.link_account(ann, "chat", "U-BOB", bob.id)
    await intake.link_account(ann, "forge", "bob-gh", bob.id)
    await intake.link_account(ann, "chat", "U-ANN", ann.user_id)

    await tenancy.members.remove_member(ann, bob.id)
    await run_member_left(container)

    assert await intake.get_links(ann, bob.id) == ()
    assert await links.read_link(ann.org_id, "chat", "U-BOB") is None
    assert await links.read_link(ann.org_id, "forge", "bob-gh") is None
    assert [link.external_id for link in await intake.get_links(ann, ann.user_id)] == ["U-ANN"]
    # A rerun finds nothing left.
    assert await intake.forget_member(ann, bob.id) == 0
    # No account links to the user who left, so none of theirs comes back.
    with pytest.raises(NotFound):
        await intake.link_account(ann, "chat", "U-BOB", bob.id)

    # Added back, Bob is a new user of the org, and his account links to him.
    again = await add_bob(container)
    assert again.id != bob.id
    relinked = await intake.link_account(ann, "chat", "U-BOB", again.id)
    assert relinked.user_id == again.id


async def test_a_deleted_account_leaves_no_link_in_a_team_org(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    intake = container.intake
    links = container.storage.get_intake_storage()
    ann = await sign_in(container)
    await add_bob(container)
    bob = await bob_signs_in(container, ann.org_id)
    await intake.link_account(ann, "chat", "U-BOB", bob.user_id)
    await intake.link_account(ann, "forge", "bob-gh", bob.user_id)

    await container.managers.tenancy.org.delete_account(bob, "bob@example.test")
    await run_member_left(container)

    assert await links.read_link(ann.org_id, "chat", "U-BOB") is None
    assert await links.read_link(ann.org_id, "forge", "bob-gh") is None
    assert await intake.get_links(ann, bob.user_id) == ()


async def test_a_member_who_holds_a_place_keeps_their_links(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    intake = container.intake
    ann = await sign_in(container)
    bob = await add_bob(container)
    await intake.link_account(ann, "chat", "U-BOB", bob.id)

    assert await intake.forget_member(ann, bob.id) == 0
    assert [link.external_id for link in await intake.get_links(ann, bob.id)] == ["U-BOB"]
