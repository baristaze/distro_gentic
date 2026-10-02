"""A host against the live app, in process: it enrolls once with its
tenant's token and resumes with its own credential after that, rotates the
credential at half its life, is handed only the work pinned to its pool,
holds each item to its owner's ceilings before anything runs, and is handed
nothing while it reads a version below the floor."""

import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from host_support import Stack, probes

from acme.apps.host.agent import ExecutorInterface, HostAgent, NotEnrolled
from acme.apps.host.ceilings import Ask, Ceilings
from acme.apps.host.config import load_credential
from acme.client.client import ApiError
from acme.client.types import ClaimedWorkView, IsolationMode
from acme.om.base import new_id, utcnow
from acme.om.hosts import rules
from acme.om.hosts.rules import WireType
from acme.om.placement.rules import pool_lane
from acme.om.placement.types.work import WorkspaceOperation
from acme.om.work.types.work_item import WorkItem, WorkKind

PROJECT = new_id()
CEILINGS = Ceilings(
    projects=frozenset({PROJECT}),
    min_isolation=IsolationMode.container,
    egress=frozenset({"github.com:443"}),
    readable=("/srv/work",),
)


class Recording(ExecutorInterface):
    def __init__(self) -> None:
        self.ran: list[ClaimedWorkView] = []

    async def run(self, item: ClaimedWorkView, ask: Ask) -> None:
        self.ran.append(item)

    async def refuse(self, item: ClaimedWorkView, reasons: list[str]) -> None:
        return None

    def stop(self, item_id: UUID, kind: str) -> bool:
        return False


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


def agent(
    api: Stack,
    home: Path,
    token: str | None,
    executor: Recording | None = None,
    clock: Clock | None = None,
) -> HostAgent:
    return HostAgent(
        api.settings(home, token),
        CEILINGS,
        probes(IsolationMode.container),
        api.client,
        executor,
        now=clock or (lambda: datetime.now(UTC)),
    )


async def enqueue(api: Stack, kind: WorkKind, payload: dict[str, Any], lane: str) -> WorkItem:
    """An item as a producer will write it, with the fields a host reads of
    what it asks (`ceilings.ask_of`), on the lane placement gives it. It is
    landed in the queue directly: the payloads of today's kinds carry where
    an item runs and nothing yet of what it asks."""
    now = utcnow()
    owner = api.owner
    item = WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=owner.user_id,
        updated_by=owner.user_id,
        kind=kind,
        target_id=new_id(),
        idempotency_key=new_id(),
        request_id=new_id(),
        payload=payload,
        lane=lane,
        available_at=now,
    )
    await api.container.storage.get_work_storage().create_item(owner.org_id, item)
    return item


def an_item(api: Stack, kind: WorkKind, payload: dict[str, Any]) -> WorkItem:
    now = utcnow()
    return WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=api.owner.user_id,
        updated_by=api.owner.user_id,
        kind=kind,
        target_id=new_id(),
        idempotency_key=new_id(),
        request_id=new_id(),
        payload=payload,
        available_at=now,
    )


def fitting(**fields: Any) -> dict[str, Any]:
    return {
        "project_id": str(PROJECT),
        "isolation": "container",
        "egress": ["github.com:443"],
        "reads": [],
        "by_person": False,
        **fields,
    }


async def test_a_host_enrolls_once_and_resumes_with_its_own_credential(
    api: Stack, tmp_path: Path
) -> None:
    pool = await api.pool()
    token = await api.token(pool.id)
    first = agent(api, tmp_path, token)
    await first.start()
    held = first.credential
    assert held.token.startswith("hst_") and held.pool_id == str(pool.id)
    path = tmp_path / "credential.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert token not in path.read_text()
    # Started again with no token at all, it resumes with what it holds.
    again = agent(api, tmp_path, None)
    await again.start()
    assert again.credential.token == held.token
    hosts = await api.container.managers.hosts.get_hosts(api.owner, pool.id)
    assert [status.host.id for status in hosts] == [UUID(held.host_id)]
    assert hosts[0].host.advertisement.isolation_modes == ("container",)


async def test_a_host_with_no_credential_and_no_token_does_not_start(
    api: Stack, tmp_path: Path
) -> None:
    with pytest.raises(NotEnrolled):
        await agent(api, tmp_path, None).start()


async def test_a_host_rotates_its_credential_at_half_its_life(api: Stack, tmp_path: Path) -> None:
    pool = await api.pool()
    clock = Clock()
    host = agent(api, tmp_path, await api.token(pool.id), clock=clock)
    await host.start()
    first = host.credential
    assert not await host.rotate_if_due()
    clock.now += (first.expires_at - first.issued_at) / 2 + timedelta(seconds=1)
    assert await host.rotate_if_due()
    assert host.credential.token != first.token
    kept = load_credential(tmp_path / "credential.json")
    assert kept is not None and kept.token == host.credential.token
    await host.beat()


async def test_a_host_runs_only_its_pools_work_and_only_within_its_ceilings(
    api: Stack, tmp_path: Path
) -> None:
    ours, theirs = await api.pool("a"), await api.pool("b")
    ran = Recording()
    host = agent(api, tmp_path, await api.token(ours.id), executor=ran)
    await host.start()
    prepare = {"operation": WorkspaceOperation.PREPARE.value, "pool_id": str(ours.id)}
    fits = await enqueue(api, WorkKind.WORKSPACE, {**prepare, **fitting()}, pool_lane(ours.id))
    await enqueue(
        api,
        WorkKind.WORKSPACE,
        {**prepare, "pool_id": str(theirs.id), **fitting()},
        pool_lane(theirs.id),
    )
    persons = await enqueue(
        api, WorkKind.WORKSPACE, {**prepare, **fitting(by_person=True)}, pool_lane(ours.id)
    )
    # Where it runs, and nothing of what it asks.
    silent = await api.container.managers.work.enqueue(
        api.owner, an_item(api, WorkKind.WORKSPACE, prepare)
    )
    handled = []
    while (one := await host.tick()) is not None:
        handled.append(one)
    by_id = {one.item.id: one.refused for one in handled}
    assert set(by_id) == {fits.id, persons.id, silent.id}
    assert by_id[fits.id] == []
    assert by_id[persons.id] == ["a person's command, which this host does not accept"]
    assert len(by_id[silent.id]) == 4
    assert [item.id for item in ran.ran] == [fits.id]


async def test_a_host_below_the_floor_is_handed_nothing(
    api: Stack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = await api.pool()
    ran = Recording()
    host = agent(api, tmp_path, await api.token(pool.id), executor=ran)
    await host.start()
    await api.container.managers.work.enqueue(
        api.owner,
        an_item(
            api,
            WorkKind.WORKSPACE,
            {"operation": WorkspaceOperation.PREPARE.value, "pool_id": str(pool.id)},
        ),
    )
    monkeypatch.setitem(rules.WIRE_FLOOR, WireType.EXEC, 2)
    with pytest.raises(ApiError) as refused:
        await host.claim_once()
    assert (refused.value.status, refused.value.code) == (426, "version_below_floor")
    assert ran.ran == []
