"""A product's claimant over the live app, in memory: its tenant's owner
issues a token of its kind for a pool, and the claimant enrolls with it,
gets a rotating credential under its kind's prefix, and claims, reads,
renews, and reports its kind's items through the gateway, with that
credential alone. It is handed nothing of another pool or another tenant,
its credential opens no other kind's path, and a revoked one is refused.
While it holds an item it appends to its kind's stream for it, which a
member of the item's tenant reads by a handle, and nobody else reads.
The example is a `render` job on a `batch` pool, and its log."""

import base64
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import SMALL_BUDGET, build_container, client_over, seed_request, sign_in
from tenant_support import person, tenant

from acme.om.base import Platform, new_id, utcnow
from acme.om.context import Permission, Role, TenantContext
from acme.om.placement.kinds import ClaimantKindSpec
from acme.om.placement.types.claimant import Claimant
from acme.om.root import PlatformPorts, ProductKinds
from acme.om.watch.kinds import MAX_APPEND_BYTES, MAX_APPEND_ENTRIES, StreamKind
from acme.om.work.kinds import WorkKindSpec
from acme.om.work.types.work_item import WorkItem, WorkStatus
from acme.services.api.container import AppContainer

RENDER = "RENDER"
BATCH = "batch"
PROBE = "probe"
LOG = "render_log"
KEY = "k" * 32
CLAIMANT_APP = {"X-App": "api", "X-App-Version": "node@test"}
PROBED = {"os": "Linux 6.8", "shell": "/bin/bash", "capabilities": [], "isolation_modes": []}


class RenderPayload(Platform):
    pool_id: UUID
    frames: int


def batch_lane(pool_id: UUID) -> str:
    return f"batch:{pool_id}"


def _render_lane(payload: RenderPayload) -> str:
    return batch_lane(payload.pool_id)


def _batch_claims(node: Claimant) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return ((batch_lane(node.pool_id), (RENDER,)),)


PRODUCT = ProductKinds(
    work=(WorkKindSpec(RENDER, RenderPayload, Permission.WRITE, _render_lane, claimant=BATCH),),
    claimants=(
        ClaimantKindSpec(BATCH, _batch_claims, prefix="bat_"),
        ClaimantKindSpec(PROBE, lambda _: (), prefix="prb_"),
    ),
    streams=(
        # A render's log, which its batch node writes: four entries a stream.
        StreamKind(LOG, entries=4, bytes=64 * 1024, streams=2, claimant=BATCH),
        StreamKind("probe_log", entries=4, bytes=4096, streams=2, claimant=PROBE),
        StreamKind("render_index", entries=4, bytes=4096, streams=2),
    ),
)


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    return build_container(tmp_path, ports=PlatformPorts(kinds=PRODUCT), live_read_key=KEY)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **CLAIMANT_APP}


async def a_pool(client: httpx.AsyncClient, owner: dict[str, str]) -> str:
    created = await client.post(
        "/v1/host-pools",
        headers={**owner, "Idempotency-Key": str(uuid4())},
        json={"name": "batch", "region": "eu-west"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def a_token(
    client: httpx.AsyncClient, owner: dict[str, str], pool_id: str, kind: str | None = BATCH
) -> str:
    body = None if kind is None else {"kind": kind}
    issued = await client.post(
        f"/v1/host-pools/{pool_id}/enrollment-tokens", headers=owner, json=body
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["enrollment"]["kind"] == (kind or "host")
    return issued.json()["token"]


async def a_node(client: httpx.AsyncClient, token: str, name: str = "node-1") -> dict[str, Any]:
    enrolled = await client.post(
        "/v1/claimants/enrollments", headers=bearer(token), json={"name": name}
    )
    assert enrolled.status_code == 200, enrolled.text
    return enrolled.json()


async def tenant_of(container: AppContainer, headers: dict[str, str]) -> TenantContext:
    token = headers["Authorization"].removeprefix("Bearer ")
    return await container.managers.tenancy.authenticate(seed_request(), token)


async def a_render(container: AppContainer, ctx: TenantContext, pool_id: str) -> WorkItem:
    now = utcnow()
    item = WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        kind=RENDER,
        target_id=new_id(),
        idempotency_key=new_id(),
        request_id=new_id(),
        payload={"pool_id": pool_id, "frames": 24},
        available_at=now,
    )
    return await container.managers.work.enqueue(ctx, item)


async def test_a_products_claimant_enrolls_and_claims_extends_and_reports_through_the_gateway(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    pool_id = await a_pool(client, owner)
    token = await a_token(client, owner, pool_id)
    # The kind and the pool are the token's: a claimant that names either is
    # refused.
    for named in ({"kind": "host"}, {"pool_id": str(uuid4())}):
        refused = await client.post(
            "/v1/claimants/enrollments", headers=bearer(token), json={"name": "n", **named}
        )
        assert refused.status_code == 422, refused.text
    node = await a_node(client, token)
    assert node["token"].startswith("bat_")
    assert (node["kind"], node["pool_id"]) == (BATCH, pool_id)

    ctx = await tenant_of(container, owner)
    render = await a_render(container, ctx, pool_id)
    claimed = await client.post("/v1/claimants/me/claims", headers=bearer(node["token"]))
    assert claimed.status_code == 200, claimed.text
    item = claimed.json()["item"]
    assert (item["id"], item["kind"], item["org_id"]) == (str(render.id), RENDER, str(ctx.org_id))
    assert item["status"] == WorkStatus.CLAIMED and item["claim_token"] is not None
    held = {**bearer(node["token"]), "Claim-Token": item["claim_token"]}

    read = await client.get(f"/v1/claimants/me/items/{render.id}", headers=held)
    assert read.status_code == 200 and read.json()["payload"]["frames"] == 24, read.text
    renewed = await client.post(
        f"/v1/claimants/me/items/{render.id}/lease",
        headers=bearer(node["token"]),
        json={"claim_token": item["claim_token"]},
    )
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["lease_expires_at"] >= item["lease_expires_at"]
    # A report is held to its shape before anything reads it.
    for off_shape in ({"outcome": "failed"}, {"outcome": "done", "error": "why"}):
        refused = await client.post(
            f"/v1/claimants/me/items/{render.id}/report",
            headers=bearer(node["token"]),
            json={"claim_token": item["claim_token"], **off_shape},
        )
        assert refused.status_code == 422, refused.text
    reported = await client.post(
        f"/v1/claimants/me/items/{render.id}/report",
        headers=bearer(node["token"]),
        json={"claim_token": item["claim_token"], "outcome": "done"},
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["status"] == WorkStatus.DONE
    after = await client.get(f"/v1/claimants/me/items/{render.id}", headers=held)
    assert after.status_code == 404, after.text

    # It rotates its credential: the next one claims, and the last one lands
    # for its grace.
    rotated = await client.post("/v1/claimants/me/credentials", headers=bearer(node["token"]))
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["token"].startswith("bat_")
    assert rotated.json()["claimant_id"] == node["claimant_id"]
    for credential in (rotated.json()["token"], node["token"]):
        empty = await client.post("/v1/claimants/me/claims", headers=bearer(credential))
        assert empty.status_code == 200 and empty.json() == {"item": None}, empty.text


async def test_a_claimants_credential_crosses_no_kind_pool_or_tenant_and_a_revoked_one_is_refused(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    ours, elsewhere = await a_pool(client, owner), await a_pool(client, owner)
    node = await a_node(client, await a_token(client, owner, ours))
    host_token = await a_token(client, owner, ours, kind=None)
    host = await client.post(
        "/v1/hosts/enrollments",
        headers=bearer(host_token),
        json={"name": "host-1", "advertisement": PROBED, "exec_version": 1},
    )
    assert host.status_code == 200, host.text

    # Another pool's render, and another tenant's routed into this pool,
    # are never handed to it.
    ajax = await tenant_of(container, owner)
    beta, _ = await container.managers.tenancy.bootstrap(
        seed_request(), "Beta", "beta", "bea@beta.test", "Bea"
    )
    other_pool = await a_render(container, ajax, elsewhere)
    stray = await a_render(container, beta, ours)
    claimed = await client.post("/v1/claimants/me/claims", headers=bearer(node["token"]))
    assert claimed.status_code == 200 and claimed.json() == {"item": None}, claimed.text
    assert (await container.managers.work.get_item(beta, stray.id)).status is WorkStatus.FAILED
    waiting = await container.managers.work.get_item(ajax, other_pool.id)
    assert waiting.status is WorkStatus.QUEUED

    # Each credential opens its own kind's path alone.
    crossings = (
        ("/v1/claimants/me/claims", host.json()["token"], None),
        ("/v1/hosts/me/claims", node["token"], {"exec_version": 1}),
        ("/v1/claimants/enrollments", host_token, {"name": "n"}),
        (
            "/v1/hosts/enrollments",
            await a_token(client, owner, ours),
            {"name": "h", "advertisement": PROBED, "exec_version": 1},
        ),
        ("/v1/claimants/me/claims", owner["Authorization"].removeprefix("Bearer "), None),
    )
    for path, credential, body in crossings:
        refused = await client.post(path, headers=bearer(credential), json=body)
        assert refused.status_code == 401, f"{path}: {refused.text}"
    tenant_route = await client.get("/v1/host-pools", headers=bearer(node["token"]))
    assert tenant_route.status_code == 401, tenant_route.text
    listed = await client.get(f"/v1/host-pools/{ours}/hosts", headers=owner)
    assert [h["id"] for h in listed.json()] == [host.json()["host_id"]], "it is no host"

    # Revoked, it is refused at once, and a host's route never revokes it.
    as_host = await client.delete(f"/v1/hosts/{node['claimant_id']}", headers=owner)
    assert as_host.status_code == 404, as_host.text
    revoked = await client.delete(f"/v1/claimants/{node['claimant_id']}", headers=owner)
    assert revoked.status_code == 200, revoked.text
    assert (revoked.json()["kind"], revoked.json()["revoked_at"] is not None) == (BATCH, True)
    after = await client.post("/v1/claimants/me/claims", headers=bearer(node["token"]))
    assert after.status_code == 401, after.text


async def test_an_owner_lists_a_pools_claimants_and_revokes_one_by_the_id_the_list_gives(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    pool_id = await a_pool(client, owner)
    node = await a_node(client, await a_token(client, owner, pool_id), name="node-7")
    host = await client.post(
        "/v1/hosts/enrollments",
        headers=bearer(await a_token(client, owner, pool_id, kind=None)),
        json={"name": "host-1", "advertisement": PROBED, "exec_version": 1},
    )
    assert host.status_code == 200, host.text

    listed = await client.get(f"/v1/host-pools/{pool_id}/claimants", headers=owner)
    assert listed.status_code == 200, listed.text
    kinds = {found["kind"]: found for found in listed.json()}
    assert set(kinds) == {BATCH, "host"}, listed.text
    assert kinds["host"]["id"] == host.json()["host_id"]
    ours = kinds[BATCH]
    assert (ours["name"], ours["pool_id"], ours["revoked_at"]) == ("node-7", pool_id, None)
    assert ours["last_seen_at"] is not None

    # A member of another tenant reads nothing of the pool.
    beta = await tenant(client, container, "beta")
    theirs = await a_pool(client, beta.owner)
    for outsider in (beta.owner, await person(client, container, beta.org_id, Role.MEMBER)):
        crossed = await client.get(f"/v1/host-pools/{pool_id}/claimants", headers=outsider)
        assert crossed.status_code == 404, crossed.text
        own = await client.get(f"/v1/host-pools/{theirs}/claimants", headers=outsider)
        assert own.status_code == 200 and own.json() == [], own.text

    # The id the list gives revokes it, and the list shows it revoked.
    revoked = await client.delete(f"/v1/claimants/{ours['id']}", headers=owner)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["id"] == node["claimant_id"]
    refused = await client.post("/v1/claimants/me/claims", headers=bearer(node["token"]))
    assert refused.status_code == 401, refused.text
    after = await client.get(f"/v1/host-pools/{pool_id}/claimants", headers=owner)
    shown = {found["id"]: found for found in after.json()}
    assert shown[ours["id"]]["revoked_at"] is not None
    assert shown[kinds["host"]["id"]]["revoked_at"] is None


def entries(*texts: str, start: int = 0) -> list[dict[str, Any]]:
    return [
        {"n": start + n, "data": base64.b64encode(text.encode()).decode()}
        for n, text in enumerate(texts)
    ]


async def held_render(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str], node: dict[str, Any]
) -> tuple[WorkItem, str]:
    """A render of the node's pool, claimed by the node: the item, and its
    claim token."""
    ctx = await tenant_of(container, owner)
    render = await a_render(container, ctx, node["pool_id"])
    claimed = await client.post("/v1/claimants/me/claims", headers=bearer(node["token"]))
    assert claimed.status_code == 200 and claimed.json()["item"]["id"] == str(render.id)
    return render, claimed.json()["item"]["claim_token"]


async def append(
    client: httpx.AsyncClient,
    node: dict[str, Any],
    item_id: UUID,
    claim_token: str,
    stream: UUID,
    sent: list[dict[str, Any]],
    kind: str = LOG,
) -> httpx.Response:
    return await client.post(
        f"/v1/claimants/me/items/{item_id}/streams/{kind}",
        headers=bearer(node["token"]),
        json={"claim_token": claim_token, "stream": str(stream), "entries": sent},
    )


async def read(
    client: httpx.AsyncClient,
    viewer: dict[str, str],
    item_id: UUID,
    after: tuple[str, ...] = (),
) -> dict[str, list[tuple[int, str]]]:
    """What a viewer reads of the item's log by a handle: each open stream's
    entries, decoded."""
    opened = await client.post(f"/v1/work-items/{item_id}/streams/{LOG}/live", headers=viewer)
    assert opened.status_code == 200, opened.text
    page = await client.get(
        "/v1/live/items", params={"handle": opened.json()["handle"], "after": list(after)}
    )
    assert page.status_code == 200, page.text
    assert (page.json()["item_id"], page.json()["kind"]) == (str(item_id), LOG)
    return {
        found["stream"]: [
            (entry["n"], base64.b64decode(entry["data"]).decode()) for entry in found["entries"]
        ]
        for found in page.json()["streams"]
    }


async def test_a_claimant_appends_to_its_kinds_stream_for_the_item_it_holds_and_a_member_reads_it(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    pool_id = await a_pool(client, owner)
    node = await a_node(client, await a_token(client, owner, pool_id))
    render, claim_token = await held_render(client, container, owner, node)
    stream = uuid4()

    appended = await append(client, node, render.id, claim_token, stream, entries("f0", "f1"))
    assert appended.status_code == 204, appended.text
    # An entry sent again lands nothing.
    again = await append(client, node, render.id, claim_token, stream, entries("again", start=1))
    assert again.status_code == 204, again.text

    member = await person(
        client, container, (await tenant_of(container, owner)).org_id, Role.MEMBER
    )
    assert await read(client, member, render.id) == {str(stream): [(0, "f0"), (1, "f1")]}
    assert await read(client, member, render.id, (f"{stream}:0",)) == {str(stream): [(1, "f1")]}

    # Past the kind's four entries the oldest goes, never the newest.
    more = await append(
        client, node, render.id, claim_token, stream, entries("f2", "f3", "f4", start=2)
    )
    assert more.status_code == 204, more.text
    held = await read(client, member, render.id)
    assert held == {str(stream): [(1, "f1"), (2, "f2"), (3, "f3"), (4, "f4")]}


async def test_a_claimant_appends_only_for_an_item_it_holds_to_a_kind_its_own_kind_writes(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    pool_id = await a_pool(client, owner)
    token = await a_token(client, owner, pool_id)
    ours, theirs = await a_node(client, token, "node-1"), await a_node(client, token, "node-2")
    mine, mine_token = await held_render(client, container, owner, ours)
    other, other_token = await held_render(client, container, owner, theirs)
    beta, _ = await container.managers.tenancy.bootstrap(
        seed_request(), "Beta", "beta", "bea@beta.test", "Bea"
    )
    elsewhere = await a_render(container, beta, pool_id)
    stream = uuid4()

    # Another claimant's item, under its token or its own, and another
    # tenant's are not found.
    for item_id, claim_token in (
        (other.id, other_token),
        (other.id, mine_token),
        (elsewhere.id, mine_token),
    ):
        refused = await append(client, ours, item_id, claim_token, stream, entries("x"))
        assert refused.status_code == 404, refused.text
    # Another claimant kind's stream, one no claimant writes, the step's,
    # and one nobody registered are not found; a name no kind could carry
    # is refused at the door.
    for kind, status in (
        ("probe_log", 404),
        ("render_index", 404),
        ("step", 404),
        ("nothing", 404),
        ("Render-Log", 422),
    ):
        refused = await append(client, ours, mine.id, mine_token, stream, entries("x"), kind)
        assert refused.status_code == status, f"{kind}: {refused.text}"

    # Its lease lapsed, it holds the item no longer until it renews it.
    ctx = await tenant_of(container, owner)
    claimed = await container.managers.work.get_item(ctx, mine.id)
    await container.managers.work.extend_lease(ctx, claimed, timedelta(seconds=-1))
    lapsed = await append(client, ours, mine.id, mine_token, stream, entries("late"))
    assert lapsed.status_code == 409, lapsed.text
    renewed = await client.post(
        f"/v1/claimants/me/items/{mine.id}/lease",
        headers=bearer(ours["token"]),
        json={"claim_token": mine_token},
    )
    assert renewed.status_code == 200, renewed.text
    landed = await append(client, ours, mine.id, mine_token, stream, entries("held"))
    assert landed.status_code == 204, landed.text

    # Handed back, it is not found.
    reported = await client.post(
        f"/v1/claimants/me/items/{mine.id}/report",
        headers=bearer(ours["token"]),
        json={"claim_token": mine_token, "outcome": "done"},
    )
    assert reported.status_code == 200, reported.text
    released = await append(client, ours, mine.id, mine_token, stream, entries("after", start=1))
    assert released.status_code == 404, released.text

    # Under a revoked credential, the item it held is written no more.
    revoked = await client.delete(f"/v1/claimants/{theirs['claimant_id']}", headers=owner)
    assert revoked.status_code == 200, revoked.text
    gone = await append(client, theirs, other.id, other_token, stream, entries("x"))
    assert gone.status_code == 401, gone.text

    # Of every refused append, nothing landed.
    assert await read(client, owner, mine.id) == {str(stream): [(0, "held")]}
    assert await read(client, owner, other.id) == {}


async def test_a_member_of_another_tenant_reads_nothing_of_an_items_stream(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    pool_id = await a_pool(client, owner)
    node = await a_node(client, await a_token(client, owner, pool_id))
    render, claim_token = await held_render(client, container, owner, node)
    landed = await append(client, node, render.id, claim_token, uuid4(), entries("ours"))
    assert landed.status_code == 204, landed.text

    beta = await tenant(client, container, "beta")
    for outsider in (beta.owner, await person(client, container, beta.org_id, Role.MEMBER)):
        crossed = await client.post(
            f"/v1/work-items/{render.id}/streams/{LOG}/live", headers=outsider
        )
        assert crossed.status_code == 404, crossed.text
    # Nor does a handle a byte off, or none at all.
    opened = await client.post(f"/v1/work-items/{render.id}/streams/{LOG}/live", headers=owner)
    handle = opened.json()["handle"]
    forged = ("B" if handle.startswith("A") else "A") + handle[1:]
    for bad in (forged, "not-a-handle"):
        refused = await client.get("/v1/live/items", params={"handle": bad})
        assert refused.status_code == 401, refused.text
    # A kind no claimant writes opens no handle.
    for kind in ("render_index", "step"):
        closed = await client.post(f"/v1/work-items/{render.id}/streams/{kind}/live", headers=owner)
        assert closed.status_code == 404, closed.text


async def test_an_append_is_held_to_its_size_before_anything_lands(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    pool_id = await a_pool(client, owner)
    node = await a_node(client, await a_token(client, owner, pool_id))
    render, claim_token = await held_render(client, container, owner, node)
    half = "x" * (MAX_APPEND_BYTES // 2 + 1)
    for sent in (
        entries(*(["e"] * (MAX_APPEND_ENTRIES + 1))),
        entries("x" * (MAX_APPEND_BYTES + 1)),
        entries(half, half),
        [{"n": 0, "data": "not base64!"}],
        [],
    ):
        refused = await append(client, node, render.id, claim_token, uuid4(), sent)
        assert refused.status_code == 422, refused.text
    assert await read(client, owner, render.id) == {}
    whole = await append(
        client, node, render.id, claim_token, uuid4(), entries("x" * MAX_APPEND_BYTES)
    )
    assert whole.status_code == 204, whole.text


async def test_an_append_spends_the_claimants_budget_of_writes(tmp_path: Path) -> None:
    container = build_container(
        tmp_path,
        ports=PlatformPorts(kinds=PRODUCT),
        live_read_key=KEY,
        credential_rate_limit_writes=SMALL_BUDGET,
    )
    async with client_over(container) as client:
        owner = await sign_in(client, container)
        pool_id = await a_pool(client, owner)
        node = await a_node(client, await a_token(client, owner, pool_id))
        render, claim_token = await held_render(client, container, owner, node)
        stream = uuid4()
        # The claim spent one write of the budget.
        for n in range(SMALL_BUDGET - 1):
            landed = await append(
                client, node, render.id, claim_token, stream, entries("e", start=n)
            )
            assert landed.status_code == 204, landed.text
        refused = await append(client, node, render.id, claim_token, stream, entries("e", start=9))
        assert refused.status_code == 429, refused.text
        assert "Retry-After" in refused.headers
        held = await read(client, owner, render.id)
    assert [n for n, _ in held[str(stream)]] == list(range(SMALL_BUDGET - 1))
