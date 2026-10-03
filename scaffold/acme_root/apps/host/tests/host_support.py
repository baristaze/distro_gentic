"""The whole API in-process behind a host: the app runs inside its lifespan,
and the host's client reaches it through a transport that streams each
answer as the app sends it, as a server does, and stamps its `Date`, as the
server in front of it does."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from email.utils import format_datetime
from pathlib import Path
from uuid import UUID

import httpx
from api_support import build_container, seed_request
from fastapi import FastAPI

from acme.apps.host.config import Settings
from acme.apps.host.probe import Probe, Probes, platform_and_clock
from acme.client.client import ApiClient
from acme.client.types import IsolationMode
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.hosts.types.pool import HostPool
from acme.services.api.app import create_app
from acme.services.api.container import AppContainer


class Streamed(httpx.AsyncBaseTransport):
    """The app in-process, its answer handed over once it starts and its
    body as it is sent: httpx's own ASGI transport holds an answer until the
    app ends it, which a control stream never does by itself. Closing the
    answer is the client going away."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = b"".join([chunk async for chunk in request.stream])  # type: ignore[union-attr]
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(key.lower(), value) for key, value in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port),
            "client": ("127.0.0.1", 123),
            "root_path": "",
        }
        chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        started: asyncio.Future[tuple[int, list[tuple[bytes, bytes]]]] = (
            asyncio.get_running_loop().create_future()
        )
        gone = asyncio.Event()
        asked = False

        async def receive() -> dict[str, object]:
            nonlocal asked
            if not asked:
                asked = True
                return {"type": "http.request", "body": body, "more_body": False}
            await gone.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            if message["type"] == "http.response.start":
                started.set_result((message["status"], message.get("headers", [])))  # type: ignore[arg-type]
            elif message["type"] == "http.response.body":
                if message.get("body"):
                    await chunks.put(message["body"])  # type: ignore[arg-type]
                if not message.get("more_body"):
                    await chunks.put(None)

        async def serve() -> None:
            try:
                await self._app(scope, receive, send)  # type: ignore[arg-type]
            except Exception as error:
                if not started.done():
                    started.set_exception(error)
            finally:
                await chunks.put(None)

        task = asyncio.ensure_future(serve())
        status, headers = await started

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                while (chunk := await chunks.get()) is not None:
                    yield chunk

            async def aclose(self) -> None:
                gone.set()
                task.cancel()

        return httpx.Response(status, headers=headers, stream=Body())


class Dated(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        response.headers["Date"] = format_datetime(utcnow(), usegmt=True)
        return response


def passing(name: str) -> Probe:
    return Probe(name, True, "passed in the test")


def failing(name: str) -> Probe:
    return Probe(name, False, "failed in the test")


def probes(*modes: IsolationMode) -> Probes:
    """The startup's own probes of the machine, each passing, and the
    platform's real one; the isolation probes pass for `modes` alone."""
    return Probes(
        trust_store=lambda: passing("trust_store"),
        proxy=lambda: passing("proxy"),
        platform_and_clock=platform_and_clock,
        isolation={
            mode: (lambda m=mode: passing(m.value) if m in modes else failing(m.value))
            for mode in IsolationMode
        },
        capabilities={"git": lambda: True},
    )


@dataclass
class Stack:
    container: AppContainer
    transport: httpx.AsyncBaseTransport
    owner: TenantContext

    def client(self, token: str | None) -> ApiClient:
        return ApiClient(
            "http://test", app="api", app_version="host@test", token=token, transport=self.transport
        )

    def settings(self, home: Path, token: str | None) -> Settings:
        return Settings(
            api_url="http://test",
            home=home,
            name="host-1",
            enrollment_token=token,
            workspace_user=None,
        )

    async def pool(self, name: str = "build") -> HostPool:
        now = utcnow()
        pool = HostPool(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=self.owner.user_id,
            updated_by=self.owner.user_id,
            name=name,
            region="eu-west",
        )
        return await self.container.managers.hosts.create_pool(self.owner, pool)

    async def token(self, pool_id: UUID) -> str:
        issued = await self.container.managers.hosts.issue_enrollment_token(self.owner, pool_id)
        return issued.token


@asynccontextmanager
async def stack(tmp_path: Path) -> AsyncIterator[Stack]:
    container = build_container(tmp_path)
    app: FastAPI = create_app(container)
    async with app.router.lifespan_context(app):
        owner, _ = await container.managers.tenancy.bootstrap(
            seed_request(), "Ajax", "ajax", "ann@example.test", "Ann"
        )
        transport = Dated(Streamed(app))
        yield Stack(container=container, transport=transport, owner=owner)
