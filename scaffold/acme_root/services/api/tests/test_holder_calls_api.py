"""A host's and a claimant's holder's calls (ADR 0106): the calls whose
refusal costs the caller what it holds go through while its own writes, or
everyone's, are spent. A host's beat, an exec item's renewal and result, and
its answers to a workspace item carry `HOLDER_CALL`, as do a claimant's
renewal and report; the bulk writes beside them, a host's output parts and a
claimant's appends, do not."""

import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import test_claimants_api as claimants
from api_support import SMALL_BUDGET, build_container, sign_in
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport
from test_admission import hold
from test_exec_relay_api import a_held_item, declared
from test_hosts_api import ASSISTANT, PROBED, bearer

from acme.om.platform_root import PlatformPorts
from acme.om.work.types.work_item import WorkStatus
from acme.services.api.app import create_app
from acme.services.api.container import AppContainer
from acme.services.api.gateway.admission import holder_call

HOLDER_CALLS = {
    ("POST", "/v1/hosts/me/heartbeats"),
    ("POST", "/v1/hosts/me/exec/{item_id}/lease"),
    ("POST", "/v1/hosts/me/exec/{item_id}/upload"),
    ("POST", "/v1/hosts/me/exec/{item_id}/result"),
    ("POST", "/v1/hosts/me/workspaces/{item_id}"),
    ("POST", "/v1/hosts/me/workspaces/{item_id}/released"),
    ("POST", "/v1/hosts/me/workspaces/{item_id}/snapshot"),
    ("POST", "/v1/claimants/me/items/{item_id}/lease"),
    ("POST", "/v1/claimants/me/items/{item_id}/report"),
}
"""The calls of a host and of a claimant that keep or settle what it holds."""

WRITES = 2
"""Two writes in flight, so two held requests fill the write lane."""


@asynccontextmanager
async def served(container: AppContainer) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    """The app over the container, inside its lifespan, and a client of it."""
    app = create_app(container)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


def test_a_hosts_and_a_claimants_holder_calls_are_these_and_no_bulk_write(
    tmp_path: Path,
) -> None:
    """Every route a host or a claimant calls under its own credential is
    marked a holder's call when, and only when, its refusal costs what the
    caller holds. A bulk write marked by mistake would take the lane and the
    budget a renewal needs."""
    app = create_app(build_container(tmp_path))
    own = ("/v1/hosts/me/", "/v1/claimants/me/")
    marked = {
        (method, route.path)
        for route in iter_route_contexts(app.routes)
        if (route.path or "").startswith(own)
        for method in route.methods or ()
        if any(depends.dependency is holder_call for depends in route.dependencies)
    }
    assert marked == HOLDER_CALLS


async def test_a_host_whose_output_spent_its_writes_still_renews_beats_and_settles(
    tmp_path: Path,
) -> None:
    """A host that streams a command's output spends its budget of writes on
    the parts. The renewal that keeps the item, the beat that keeps the host
    online, and the result that settles the item spend a budget of their
    own, so the burst revokes nothing the host holds."""
    container = build_container(
        tmp_path,
        agent_kinds=(ASSISTANT,),
        credential_rate_limit_writes=SMALL_BUDGET,
        credential_rate_limit_holds=SMALL_BUDGET,
    )
    async with served(container) as (_, client):
        owner = await sign_in(client, container)
        host, item_id = await a_held_item(client, owner, container)
        headers = bearer(host["token"])
        path = f"/v1/hosts/me/exec/{item_id}"
        line = b"building\n"
        part = {
            "stream": "stdout",
            "data": base64.b64encode(line).decode(),
            "crossing": declared("stream_part", line),
        }
        # The claim that took the item spent the first write.
        pushed = [
            (await client.post(f"{path}/parts", headers=headers, json={**part, "seq": seq}))
            for seq in range(SMALL_BUDGET)
        ]
        renewed = await client.post(f"{path}/lease", headers=headers)
        beat = await client.post(
            "/v1/hosts/me/heartbeats",
            headers=headers,
            json={"advertisement": PROBED, "exec_version": 2},
        )
        result = json.dumps({"outcome": {"exit_code": 0}}).encode()
        settled = await client.post(
            f"{path}/result",
            headers=headers,
            json={
                "data": base64.b64encode(result).decode(),
                "crossing": declared("result", result),
            },
        )
    assert [p.status_code for p in pushed] == [204] * (SMALL_BUDGET - 1) + [429]
    assert pushed[-1].json()["error"]["code"] == "rate_limited"
    assert renewed.status_code == 200, renewed.text
    assert beat.status_code == 200 and beat.json()["online"], beat.text
    assert settled.status_code == 204, settled.text


async def test_a_claimants_renewal_and_report_are_admitted_with_the_write_lane_full(
    tmp_path: Path,
) -> None:
    """A slowdown that fills the write lane sheds the claimant's own writes,
    a claim among them, and still admits the renewal that keeps its item and
    the report that settles it."""
    container = build_container(
        tmp_path,
        ports=PlatformPorts(kinds=claimants.PRODUCT),
        live_read_key=claimants.KEY,
        admission_limit_writes=WRITES,
    )
    async with served(container) as (app, client):
        owner = await sign_in(client, container)
        pool_id = await claimants.a_pool(client, owner)
        node = await claimants.a_node(client, await claimants.a_token(client, owner, pool_id))
        headers = claimants.bearer(node["token"])
        ctx = await claimants.tenant_of(container, owner)
        render = await claimants.a_render(container, ctx, pool_id)
        claimed = await client.post("/v1/claimants/me/claims", headers=headers)
        assert claimed.status_code == 200, claimed.text
        token = claimed.json()["item"]["claim_token"]
        first, ends_first, _ = await hold(app, client, "POST")
        second, ends_second, _ = await hold(app, client, "POST")

        shed = await client.post("/v1/claimants/me/claims", headers=headers)
        item = f"/v1/claimants/me/items/{render.id}"
        renewed = await client.post(f"{item}/lease", headers=headers, json={"claim_token": token})
        reported = await client.post(
            f"{item}/report", headers=headers, json={"claim_token": token, "outcome": "done"}
        )
        ends_first.set()
        ends_second.set()
        assert [(await held).status_code for held in (first, second)] == [200, 200]
    assert shed.status_code == 503
    assert shed.json()["error"]["message"] == "the process is at its bound of writes in flight"
    assert renewed.status_code == 200, renewed.text
    assert reported.status_code == 200 and reported.json()["status"] == WorkStatus.DONE, (
        reported.text
    )
