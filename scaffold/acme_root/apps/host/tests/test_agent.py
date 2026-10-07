"""A host against the live app, in process: it enrolls once with its
tenant's token and resumes with its own credential after that, rotates the
credential at half its life, is handed only the work pinned to its pool,
holds each item to its owner's ceilings before anything runs, and is handed
nothing while it reads a version below the floor. A failure it outlasts is
waited out with the credential it holds; a refused credential ends it."""

import asyncio
import stat
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from host_support import Stack, probes

from acme.apps.host.agent import ExecutorInterface, HostAgent
from acme.apps.host.ceilings import Ask, Ceilings
from acme.apps.host.config import BadSetting, settings_from_env
from acme.client.claimant.backoff import BACKOFF_MAX_SECONDS
from acme.client.claimant.credential import load_credential
from acme.client.claimant.enrollment import NotEnrolled
from acme.client.client import ApiClient, ApiError
from acme.client.types import ClaimedWorkView, IsolationMode
from acme.infra.workspaces.container import DEFAULT_IMAGE
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
    ceilings: Ceilings = CEILINGS,
    metadata_answers: bool = False,
) -> HostAgent:
    return HostAgent(
        api.settings(home, token),
        ceilings,
        probes(IsolationMode.container, metadata_answers=metadata_answers),
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
    assert [status.host.id for status in hosts] == [UUID(held.claimant_id)]
    assert hosts[0].host.advertisement.isolation_modes == ("container",)


def test_a_container_workspace_runs_the_engines_default_image_unless_its_owner_names_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine's default, which its container case shows holds `git`
    for a session's checkout, is the host's too."""
    monkeypatch.delenv("ACME_HOST_WORKSPACE_IMAGE", raising=False)
    assert settings_from_env().workspace_image == DEFAULT_IMAGE
    monkeypatch.setenv("ACME_HOST_WORKSPACE_IMAGE", "registry.example.test/tools:1")
    assert settings_from_env().workspace_image == "registry.example.test/tools:1"


def test_the_image_pull_has_a_limit_of_its_own_that_a_bad_value_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ACME_HOST_PULL_TIMEOUT_SECONDS", raising=False)
    assert settings_from_env().pull_timeout_seconds == 900.0
    monkeypatch.setenv("ACME_HOST_PULL_TIMEOUT_SECONDS", "1800")
    assert settings_from_env().pull_timeout_seconds == 1800.0
    for bad in ("soon", "0", "-5"):
        monkeypatch.setenv("ACME_HOST_PULL_TIMEOUT_SECONDS", bad)
        with pytest.raises(BadSetting):
            settings_from_env()


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
    await host.idle()
    by_id = {one.item.id: one.refused for one in handled}
    assert set(by_id) == {fits.id, persons.id, silent.id}
    assert by_id[fits.id] == []
    assert by_id[persons.id] == ["a person's command, which this host does not accept"]
    assert len(by_id[silent.id]) == 5
    assert [item.id for item in ran.ran] == [fits.id]


async def test_a_host_that_reaches_a_metadata_service_refuses_open_egress(
    api: Stack, tmp_path: Path
) -> None:
    pool = await api.pool()
    ran = Recording()
    wide = replace(CEILINGS, egress=None)
    host = agent(api, tmp_path, await api.token(pool.id), ran, ceilings=wide, metadata_answers=True)
    await host.start()
    prepare = {"operation": WorkspaceOperation.PREPARE.value, "pool_id": str(pool.id)}
    opened = await enqueue(
        api, WorkKind.WORKSPACE, {**prepare, **fitting(egress=None)}, pool_lane(pool.id)
    )
    listed = await enqueue(api, WorkKind.WORKSPACE, {**prepare, **fitting()}, pool_lane(pool.id))
    handled = []
    while (one := await host.tick()) is not None:
        handled.append(one)
    await host.idle()
    by_id = {one.item.id: one.refused for one in handled}
    assert by_id == {
        opened.id: ["open egress on a host that reaches its cloud's metadata service"],
        listed.id: [],
    }
    assert [item.id for item in ran.ran] == [listed.id]


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


class FailsOnce(httpx.AsyncBaseTransport):
    """The stack, except that the first call to `path` fails as `failure`
    says: an answer with that status, or the wire dropping it."""

    def __init__(self, inner: httpx.AsyncBaseTransport, path: str, failure: int | None) -> None:
        self._inner = inner
        self._path = path
        self._failure = failure
        self.failed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not self.failed and request.url.path == self._path:
            self.failed = True
            if self._failure is None:
                raise httpx.ConnectError("the connection was reset", request=request)
            error = {"error": {"code": "unavailable", "message": "try again"}}
            return httpx.Response(self._failure, json=error, headers={"retry-after": "7"})
        return await self._inner.handle_async_request(request)


@pytest.mark.parametrize("failure", [503, 429, None])
async def test_a_host_waits_out_a_failed_beat_and_goes_on_with_its_credential(
    api: Stack, tmp_path: Path, failure: int | None
) -> None:
    pool = await api.pool()
    flaky = FailsOnce(api.transport, "/v1/hosts/me/heartbeats", failure)
    ran = Recording()
    host = HostAgent(
        api.settings(tmp_path, await api.token(pool.id)),
        CEILINGS,
        probes(IsolationMode.container),
        lambda token: ApiClient(
            "http://test", app="api", app_version="host@test", token=token, transport=flaky
        ),
        ran,
        jitter=lambda: 0.0,
    )
    await host.start()
    held = host.credential
    wait = await host.turn()
    assert flaky.failed
    assert wait == (7.0 if failure is not None else 0.5)
    assert 0 < wait <= BACKOFF_MAX_SECONDS
    assert host.credential == held == load_credential(tmp_path / "credential.json")
    prepare = {"operation": WorkspaceOperation.PREPARE.value, "pool_id": str(pool.id)}
    item = await enqueue(api, WorkKind.WORKSPACE, {**prepare, **fitting()}, pool_lane(pool.id))
    assert await host.turn() == 0.0
    await host.idle()
    assert [one.id for one in ran.ran] == [item.id]
    assert await host.turn() == api.settings(tmp_path, None).beat_seconds


class Held(Recording):
    """An executor whose items run until `release` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def run(self, item: ClaimedWorkView, ask: Ask) -> None:
        await super().run(item, ask)
        await self.release.wait()


async def test_a_host_runs_no_more_items_at_once_than_its_ceilings_allow(
    api: Stack, tmp_path: Path
) -> None:
    pool = await api.pool()
    held = Held()
    host = HostAgent(
        api.settings(tmp_path, await api.token(pool.id)),
        replace(CEILINGS, items_at_once=2),
        probes(IsolationMode.container),
        api.client,
        held,
    )
    await host.start()
    prepare = {"operation": WorkspaceOperation.PREPARE.value, "pool_id": str(pool.id)}
    items = [
        await enqueue(api, WorkKind.WORKSPACE, {**prepare, **fitting()}, pool_lane(pool.id))
        for _ in range(3)
    ]
    assert await host.claim_once() is not None
    assert await host.claim_once() is not None
    # Two run side by side; a third is not claimed, so no lease waits on it.
    assert await host.claim_once() is None
    await asyncio.sleep(0)
    assert len(held.ran) == 2
    held.release.set()
    await host.idle()
    assert host.woken.is_set()  # an item that ends wakes the loop to claim
    assert await host.claim_once() is not None
    await host.idle()
    assert {one.id for one in held.ran} == {item.id for item in items}


async def test_a_refused_credential_ends_the_host(api: Stack, tmp_path: Path) -> None:
    pool = await api.pool()
    host = agent(api, tmp_path, await api.token(pool.id))
    await host.start()
    await api.container.managers.hosts.revoke_host(api.owner, UUID(host.credential.claimant_id))
    with pytest.raises(ApiError) as refused:
        await host.turn()
    assert refused.value.status == 401
