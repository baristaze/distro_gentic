"""The events manager's recent read: newest first from the head, a page at
a time back to the floor, a tenant's own stream alone, and only with read."""

import pytest
from unit.test_change_events_manager import Retention, append_aged, context, keeping

from acme.om.change_events.impl.manager import ChangeEventsManagerImpl, ChangeEventsOptions
from acme.om.change_events.storage.impl.memory import ChangeEventStorageMemoryImpl
from acme.om.change_events.types.change_event import ChangeEvent
from acme.om.context import Role
from acme.om.exceptions import NotAuthorized

from contracts.change_event_storage import make_change_event


@pytest.fixture
def retention() -> Retention:
    return Retention()  # pyright: ignore[reportAbstractUsage] (a partial double)


@pytest.fixture
def manager(retention: Retention) -> ChangeEventsManagerImpl:
    return ChangeEventsManagerImpl(
        ChangeEventStorageMemoryImpl(), retention, ChangeEventsOptions(max_limit=2)
    )


async def test_the_recent_read_pages_back_from_the_head_to_the_floor(
    retention: Retention,
) -> None:
    manager = keeping(retention, 90)
    ctx, other = context(Role.OWNER), context(Role.OWNER)
    await append_aged(manager, ctx, 100, 100, 1, 1, 1, 1, 1)
    await append_aged(manager, other, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    assert await manager.purge_across_tenants() == 2

    def seqs(events: list[ChangeEvent]) -> list[int]:
        return [e.seq for e in events]

    # Newest first from the head, then each page below the last one's oldest.
    assert seqs(await manager.get_recent_change_events(ctx, None, 2)) == [7, 6]
    assert seqs(await manager.get_recent_change_events(ctx, 6, 2)) == [5, 4]
    # The page that reaches the floor is short, and the one below it empty.
    assert seqs(await manager.get_recent_change_events(ctx, 4, 2)) == [3]
    assert await manager.get_recent_change_events(ctx, 3, 2) == []
    assert await manager.get_recent_change_events(ctx, 1, 2) == []
    # A number past the head reads from the head.
    assert seqs(await manager.get_recent_change_events(ctx, 1000, 2)) == [7, 6]
    assert seqs(await manager.get_recent_change_events(ctx, None, 1000)) == [7, 6, 5, 4, 3]
    # Every page is the caller's own: the other tenant's longer stream and
    # untrimmed bottom never show, at the head or paging back.
    assert all(
        e.org_id == ctx.org_id for e in await manager.get_recent_change_events(ctx, 1000, 1000)
    )
    assert seqs(await manager.get_recent_change_events(other, None, 1000)) == list(range(9, 0, -1))
    assert all(
        e.org_id == other.org_id for e in await manager.get_recent_change_events(other, 3, 1000)
    )
    assert await manager.get_recent_change_events(context(), None, 10) == []


async def test_the_recent_read_needs_read(manager: ChangeEventsManagerImpl) -> None:
    member = context(Role.MEMBER)
    await manager.append_change_event(member, make_change_event(member.org_id))
    no_read = member.model_copy(
        update={"security": member.security.model_copy(update={"permissions": ()})}
    )
    with pytest.raises(NotAuthorized):
        await manager.get_recent_change_events(no_read, None, 10)
