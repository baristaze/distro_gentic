"""The relay's routes over the live app, in memory. Every connection that
crosses a customer's wall is opened from inside it: each route a host calls
takes the host's own credential and nothing else, and nothing the platform
keeps or imports could call into a host. What crosses is verified by its
hash at the relay, and refused when it does not verify."""

import ast
import base64
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from api_support import build_container
from contracts.agent_session_storage import make_session
from test_hosts_api import ASSISTANT, a_host, a_pool, a_token, bearer, tenant_of

import acme.om.hosts
import acme.om.relay
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.hosts.types.host import Host
from acme.om.relay.types.exec import ExecCall, RunRequest
from acme.services.api.app import create_app
from acme.services.api.container import AppContainer
from acme.services.api.types.hosts import HostView

RUNNER = RequestContext(request_id=new_id(), app=AppContext(type=AppType.WORKER, version="t"))

HOST_ROUTES = {
    ("POST", "/v1/hosts/me/credentials"),
    ("POST", "/v1/hosts/me/heartbeats"),
    ("POST", "/v1/hosts/me/claims"),
    ("GET", "/v1/hosts/me/exec/{item_id}"),
    ("POST", "/v1/hosts/me/exec/{item_id}/parts"),
    ("POST", "/v1/hosts/me/exec/{item_id}/result"),
    ("POST", "/v1/hosts/me/exec/{item_id}/lease"),
    ("POST", "/v1/hosts/me/workspaces/{item_id}"),
    ("POST", "/v1/hosts/me/workspaces/{item_id}/released"),
    ("GET", "/v1/hosts/me/control"),
}
"""Every call a host makes once it is enrolled: each one a request it opens
from inside its wall."""

NETWORK_CLIENTS = frozenset(
    {"httpx", "aiohttp", "requests", "urllib.request", "websockets", "socket", "grpc"}
)
"""What a platform process would dial an address with."""

ADDRESSES = frozenset({"url", "address", "ip", "port", "endpoint", "callback", "hostname"})


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    return build_container(tmp_path, agent_kinds=(ASSISTANT,))


def declared(kind: str, data: bytes) -> dict[str, Any]:
    return {"kind": kind, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


async def a_held_item(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> tuple[dict[str, Any], UUID]:
    """A host that holds a session's workspace, and an exec item the runner
    sent it, claimed by the host through its route."""
    pool_id = await a_pool(client, owner)
    host = await a_host(client, await a_token(client, owner, pool_id))
    ctx = await tenant_of(container, owner)
    managers = container.managers
    session = await managers.agent_sessions.create_session(ctx, make_session())
    await managers.hosts.place_session(ctx, session.id, UUID(pool_id))
    await managers.relay.bind_workspace(ctx, session.id, UUID(host["host_id"]), "/srv/work/s1")
    epoch = await managers.steps.begin_run(ctx, session.id)
    spec = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
    call = ExecCall(
        session_id=session.id,
        key=new_id(),
        request=RunRequest(argv=("make", "deploy")),
        effect="unsafe",
        deadline=utcnow() + timedelta(minutes=5),
        epoch=epoch,
        spec=spec,
    )
    item = await managers.relay.send(RUNNER, ctx.org_id, call, 0)
    claimed = await client.post(
        "/v1/hosts/me/claims", headers=bearer(host["token"]), json={"exec_version": 1}
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["item"]["payload"]["item_id"] == str(item.id)
    return host, item.id


def test_every_call_a_host_makes_is_a_request_it_opens_with_its_own_credential(
    tmp_path: Path,
) -> None:
    paths = create_app(build_container(tmp_path)).openapi()["paths"]
    hosts_own = {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/v1/hosts/me")
        for method in operations
    }
    assert hosts_own == HOST_ROUTES


async def test_the_relays_routes_take_the_hosts_credential_and_nothing_else(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    host, item_id = await a_held_item(client, owner, container)
    enrollment = await a_token(client, owner, await a_pool(client, owner, "b"))
    person = owner["Authorization"].removeprefix("Bearer ")
    for method, path in sorted(HOST_ROUTES):
        url = path.replace("{item_id}", str(item_id))
        for headers in ({"X-App": "api"}, bearer(person), bearer(enrollment)):
            refused = await client.request(method, url, headers=headers, json={})
            assert refused.status_code == 401, (method, url, refused.text)
    held = await client.get(f"/v1/hosts/me/exec/{item_id}", headers=bearer(host["token"]))
    assert held.status_code == 200, held.text
    assert held.json()["request"] == {
        "operation": "run",
        "argv": ["make", "deploy"],
        "cwd": ".",
        "env": [],
        "secrets": [],
        "max_output": 1_000_000,
    }
    # Another host of the tenant reads nothing of an item it does not hold.
    other = await a_host(client, await a_token(client, owner, await a_pool(client, owner, "c")))
    foreign = await client.get(f"/v1/hosts/me/exec/{item_id}", headers=bearer(other["token"]))
    assert foreign.status_code == 409 and foreign.json()["error"]["code"] == "exec_not_held"


def test_nothing_the_platform_keeps_or_imports_could_call_into_a_host() -> None:
    # What it keeps of a host names no address to reach it at.
    for fields in (Host.model_fields, HostView.model_fields):
        assert not ADDRESSES & {word for name in fields for word in name.split("_")}
    # What serves a host imports no client of the network: every exchange
    # with a host is an answer to a request the host made.
    api = Path(create_app.__code__.co_filename).parent
    sources = [
        *Path(acme.om.relay.__path__[0]).rglob("*.py"),
        *Path(acme.om.hosts.__path__[0]).rglob("*.py"),
        *(api / "routers").glob("*.py"),
        *(api / "services").rglob("*.py"),
        api / "gateway" / "hosts.py",
    ]
    imported: dict[str, set[str]] = {}
    for source in sources:
        for node in ast.walk(ast.parse(source.read_text())):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                if any(name == c or name.startswith(c + ".") for c in NETWORK_CLIENTS):
                    imported.setdefault(source.name, set()).add(name)
    assert imported == {}


async def test_a_part_or_a_result_whose_hash_does_not_verify_is_refused_at_the_relay(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    host, item_id = await a_held_item(client, owner, container)
    path = f"/v1/hosts/me/exec/{item_id}"
    real, tampered = b"deployed\n", b"deployeD\n"
    part = {
        "seq": 0,
        "stream": "stdout",
        "data": base64.b64encode(tampered).decode(),
        "crossing": declared("stream_part", real),
    }
    refused = await client.post(f"{path}/parts", headers=bearer(host["token"]), json=part)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "crossing_refused"
    result = json.dumps({"outcome": {"exit_code": 0}, "output": {"stdout": "ok"}}).encode()
    forged = json.dumps({"outcome": {"exit_code": 0}, "output": {"stdout": "no"}}).encode()
    for crossing, data in (
        (declared("result", result), forged),
        (declared("stream_part", result), result),
    ):
        body = {"data": base64.b64encode(data).decode(), "crossing": crossing}
        refused = await client.post(f"{path}/result", headers=bearer(host["token"]), json=body)
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "crossing_refused"
    ctx = await tenant_of(container, owner)
    progress = await container.managers.relay.watch(RUNNER, ctx.org_id, item_id, -1)
    assert progress.parts == () and progress.outcome is None
    # The same bytes, declared as they are, land.
    part["data"] = base64.b64encode(real).decode()
    landed = await client.post(f"{path}/parts", headers=bearer(host["token"]), json=part)
    assert landed.status_code == 204, landed.text
    body = {"data": base64.b64encode(result).decode(), "crossing": declared("result", result)}
    done = await client.post(f"{path}/result", headers=bearer(host["token"]), json=body)
    assert done.status_code == 204, done.text
    progress = await container.managers.relay.watch(RUNNER, ctx.org_id, item_id, -1)
    assert [p.text for p in progress.parts] == ["deployed\n"]
    assert progress.output is not None and progress.output.stdout == "ok"
