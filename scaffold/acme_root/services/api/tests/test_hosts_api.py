"""Hosts over the live app, in memory: a pool and its enrollment token, a
host that enrolls with it and calls with a credential of its own kind and
nothing else, a claim that names nothing but the version it reads and is
handed only what is pinned to its pool, and a session pinned to the pool
that waits, visibly, while no host of it is online."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import add_member, build_container, seed_request, sign_in_as

from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id, utcnow
from acme.om.context import Role, TenantContext
from acme.om.hosts import rules
from acme.om.hosts.rules import WireType
from acme.om.placement.types.work import WorkspaceOperation
from acme.om.work.types.work_item import WorkItem, WorkKind
from acme.services.api.container import AppContainer

ASSISTANT = AgentKind(
    name="assistant",
    version=1,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=1, count=0),
)
PROBED = {
    "os": "Linux 6.8",
    "shell": "/bin/bash",
    "capabilities": ["git"],
    "isolation_modes": ["container"],
}
HOST_APP = {"X-App": "api", "X-App-Version": "host@test"}


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    return build_container(tmp_path, agent_kinds=(ASSISTANT,))


def created(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **HOST_APP}


async def a_pool(client: httpx.AsyncClient, owner: dict[str, str], name: str = "lab") -> str:
    answered = await client.post(
        "/v1/host-pools", headers=created(owner), json={"name": name, "region": "eu-west"}
    )
    assert answered.status_code == 201, answered.text
    return answered.json()["id"]


async def a_token(client: httpx.AsyncClient, owner: dict[str, str], pool_id: str) -> str:
    issued = await client.post(f"/v1/host-pools/{pool_id}/enrollment-tokens", headers=owner)
    assert issued.status_code == 200, issued.text
    assert issued.json()["enrollment"]["pool_id"] == pool_id
    return issued.json()["token"]


async def a_host(client: httpx.AsyncClient, token: str, name: str = "host-1") -> dict[str, Any]:
    enrolled = await client.post(
        "/v1/hosts/enrollments",
        headers=bearer(token),
        json={"name": name, "advertisement": PROBED, "exec_version": 1},
    )
    assert enrolled.status_code == 200, enrolled.text
    return enrolled.json()


async def tenant_of(container: AppContainer, headers: dict[str, str]) -> TenantContext:
    token = headers["Authorization"].removeprefix("Bearer ")
    return await container.managers.tenancy.authenticate(seed_request(), token)


async def prepare_in(container: AppContainer, ctx: TenantContext, pool_id: str) -> WorkItem:
    now = utcnow()
    item = WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        kind=WorkKind.WORKSPACE,
        target_id=new_id(),
        idempotency_key=new_id(),
        request_id=new_id(),
        payload={"operation": WorkspaceOperation.PREPARE.value, "pool_id": pool_id},
        available_at=now,
    )
    return await container.managers.work.enqueue(ctx, item)


async def test_a_host_enrolls_once_and_calls_with_a_credential_of_its_own(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    pool_id = await a_pool(client, owner)
    token = await a_token(client, owner, pool_id)
    assert token.startswith("hen_")
    # The pool is the token's: a host that names one is refused.
    named = await client.post(
        "/v1/hosts/enrollments",
        headers=bearer(token),
        json={"name": "h", "advertisement": PROBED, "exec_version": 1, "pool_id": str(uuid4())},
    )
    assert named.status_code == 422, named.text
    host = await a_host(client, token)
    assert host["token"].startswith("hst_") and host["pool_id"] == pool_id
    beat = await client.post(
        "/v1/hosts/me/heartbeats",
        headers=bearer(host["token"]),
        json={"advertisement": PROBED, "exec_version": 1},
    )
    assert beat.status_code == 200, beat.text
    assert beat.json()["online"] and beat.json()["advertisement"]["isolation_modes"] == [
        "container"
    ]
    listed = await client.get(f"/v1/host-pools/{pool_id}/hosts", headers=owner)
    assert [h["id"] for h in listed.json()] == [host["host_id"]]
    # The host's credential opens no tenant route, and nothing but it opens
    # a host's: not a person's session, not the enrollment token.
    tenant_route = await client.get("/v1/host-pools", headers=bearer(host["token"]))
    assert tenant_route.status_code == 401, tenant_route.text
    for credential in (owner["Authorization"].removeprefix("Bearer "), token):
        refused = await client.post(
            "/v1/hosts/me/claims", headers=bearer(credential), json={"exec_version": 1}
        )
        assert refused.status_code == 401, refused.text
    # Rotated, the next credential works, and the last one for its grace.
    rotated = await client.post("/v1/hosts/me/credentials", headers=bearer(host["token"]))
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["token"] != host["token"]
    assert rotated.json()["host_id"] == host["host_id"]
    for credential in (rotated.json()["token"], host["token"]):
        claimed = await client.post(
            "/v1/hosts/me/claims", headers=bearer(credential), json={"exec_version": 1}
        )
        assert claimed.status_code == 200 and claimed.json() == {"item": None}
    # Revoked, it is refused at once.
    revoked = await client.delete(f"/v1/hosts/{host['host_id']}", headers=owner)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
    after = await client.post(
        "/v1/hosts/me/claims", headers=bearer(rotated.json()["token"]), json={"exec_version": 1}
    )
    assert after.status_code == 401, after.text


async def test_a_claim_names_only_its_version_and_is_handed_only_its_pools_work(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ours, theirs = await a_pool(client, owner, "a"), await a_pool(client, owner, "b")
    host = await a_host(client, await a_token(client, owner, ours))
    ctx = await tenant_of(container, owner)
    elsewhere = await prepare_in(container, ctx, theirs)
    mine = await prepare_in(container, ctx, ours)
    asking = await client.post(
        "/v1/hosts/me/claims",
        headers=bearer(host["token"]),
        json={"exec_version": 1, "pool_id": theirs, "lane": f"pool:{theirs}"},
    )
    assert asking.status_code == 422, asking.text
    # A version below the floor is handed nothing.
    monkeypatch.setitem(rules.WIRE_FLOOR, WireType.EXEC, 2)
    stale = await client.post(
        "/v1/hosts/me/claims", headers=bearer(host["token"]), json={"exec_version": 1}
    )
    assert stale.status_code == 426 and stale.json()["error"]["code"] == "version_below_floor"
    monkeypatch.setitem(rules.WIRE_FLOOR, WireType.EXEC, 1)
    claimed = await client.post(
        "/v1/hosts/me/claims", headers=bearer(host["token"]), json={"exec_version": 1}
    )
    assert claimed.status_code == 200, claimed.text
    item = claimed.json()["item"]
    assert (item["id"], item["kind"], item["wire_version"]) == (str(mine.id), "WORKSPACE", 1)
    assert item["payload"]["pool_id"] == ours
    nothing = await client.post(
        "/v1/hosts/me/claims", headers=bearer(host["token"]), json={"exec_version": 1}
    )
    assert nothing.json() == {"item": None}
    assert UUID(item["id"]) != elsewhere.id


async def test_a_pinned_session_reads_waiting_until_a_host_of_its_pool_is_online(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    pool_id = await a_pool(client, owner)
    started = await client.post(
        "/v1/agent-sessions",
        headers=created(owner),
        json={"kind": "assistant", "title": "the dropped object"},
    )
    path = f"/v1/agent-sessions/{started.json()['id']}/placement"
    unplaced = await client.get(path, headers=owner)
    assert unplaced.json()["pool"] is None and not unplaced.json()["waiting"]
    pinned = await client.put(path, headers=owner, json={"pool_id": pool_id})
    assert pinned.status_code == 200, pinned.text
    assert (pinned.json()["pool"]["id"], pinned.json()["hosts_online"]) == (pool_id, 0)
    assert pinned.json()["waiting"] is True
    org_id = (await tenant_of(container, owner)).org_id
    await add_member(container, org_id, "val@example.test", Role.VIEWER)
    viewer = await sign_in_as(client, "val@example.test", org_id)
    moved = await client.put(path, headers=viewer, json={"pool_id": None})
    assert moved.status_code == 403, moved.text
    assert (await client.get(path, headers=viewer)).json()["waiting"] is True
    await a_host(client, await a_token(client, owner, pool_id))
    online = await client.get(path, headers=owner)
    assert (online.json()["hosts_online"], online.json()["waiting"]) == (1, False)
