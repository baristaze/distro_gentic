"""Admission and the control streams: the stream a host, or a product's
claimant, holds open takes no read slot, so a fleet of them never starves
the reads."""

import asyncio
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from api_support import build_container
from fastapi import FastAPI
from test_admission import READS, WRITES
from test_claimant_kit_api import PRODUCT, a_pool_token
from test_hosts_api import a_host, a_pool, a_token, bearer

from acme.om.platform_root import PlatformPorts
from acme.services.api.container import AppContainer

HOSTS = "/v1/hosts/me/control"
CLAIMANTS = "/v1/claimants/me/control"


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    """Overrides the container of `conftest`, so the `app` and `client`
    fixtures run against a process whose lanes are one and two, with a
    product's claimant kind registered."""
    return build_container(
        tmp_path,
        ports=PlatformPorts(kinds=PRODUCT),
        admission_limit_reads=READS,
        admission_limit_writes=WRITES,
    )


async def open_control(
    app: FastAPI, token: str, path: str = HOSTS
) -> tuple[asyncio.Task[None], asyncio.Event]:
    """Opens a control stream and returns it once its first line has
    arrived, so it is in flight; with the event that disconnects it. It is
    driven over ASGI directly, because the test client hands back a response
    only once its body has ended, and the stream runs for a minute."""
    opened, gone = asyncio.Event(), asyncio.Event()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"test")]
        + [(k.lower().encode(), v.encode()) for k, v in bearer(token).items()],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }
    request_sent = False

    async def receive() -> MutableMapping[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    statuses: list[int] = []

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            statuses.append(message["status"])
        elif message["type"] == "http.response.body" and message.get("body"):
            opened.set()

    stream = asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(opened.wait(), timeout=5)
    assert statuses == [200]
    return stream, gone


async def test_a_hosts_control_stream_holds_no_read_slot(
    app: FastAPI, client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    """A host holds its control stream open for a minute at a time, so a
    fleet of hosts, each holding a read slot, would starve the reads of
    every caller. More streams are open here than the read lane has slots,
    and an ordinary read is still admitted."""
    pool_id = await a_pool(client, owner)
    streams = []
    for name in ("host-1", "host-2"):
        host = await a_host(client, await a_token(client, owner, pool_id), name)
        streams.append(await open_control(app, host["token"]))
    assert len(streams) > READS

    read = await client.get("/v1/agent-sessions", headers=owner)

    assert read.status_code == 200, read.text
    for stream, gone in streams:
        gone.set()
        await asyncio.wait_for(stream, timeout=5)


async def test_a_claimants_control_stream_holds_no_read_slot(
    app: FastAPI, client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    """A product's claimant holds its control stream open as a host does,
    so it is let through as the host's is."""
    streams = []
    for name in ("scanner-1", "scanner-2"):
        _, token = await a_pool_token(client, owner)
        enrolled = await client.post(
            "/v1/claimants/enrollments", headers=bearer(token), json={"name": name}
        )
        assert enrolled.status_code == 200, enrolled.text
        streams.append(await open_control(app, enrolled.json()["token"], CLAIMANTS))
    assert len(streams) > READS

    read = await client.get("/v1/agent-sessions", headers=owner)

    assert read.status_code == 200, read.text
    for stream, gone in streams:
        gone.set()
        await asyncio.wait_for(stream, timeout=5)
