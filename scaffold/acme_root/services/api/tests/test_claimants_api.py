"""A product's claimant over the live app, in memory: its tenant's owner
issues a token of its kind for a pool, and the claimant enrolls with it,
gets a rotating credential under its kind's prefix, and claims, reads,
renews, and reports its kind's items through the gateway, with that
credential alone. It is handed nothing of another pool or another tenant,
its credential opens no other kind's path, and a revoked one is refused.
The example is a `render` job on a `batch` pool."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import build_container, seed_request

from acme.om.base import Platform, new_id, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.placement.kinds import ClaimantKindSpec
from acme.om.placement.types.claimant import Claimant
from acme.om.root import PlatformPorts, ProductKinds
from acme.om.work.kinds import WorkKindSpec
from acme.om.work.types.work_item import WorkItem, WorkStatus
from acme.services.api.container import AppContainer

RENDER = "RENDER"
BATCH = "batch"
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
    claimants=(ClaimantKindSpec(BATCH, _batch_claims, prefix="bat_"),),
)


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    return build_container(tmp_path, ports=PlatformPorts(kinds=PRODUCT))


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
